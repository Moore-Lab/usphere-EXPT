"""
experiments/coriolis_table.py  —  Coriolis measurement via rotating table

Sequence
--------
1.  Optionally save the current FPGA sphere parameters (so you can
    restore after the run).
2.  Set the table rotation via FPGA AO4/AO5 (frequency + amplitude).
3.  Wait *settle_s* seconds for the rotation to stabilise.
4.  Inject experiment metadata, FPGA register snapshot, and TIC
    pressure readings into DAQ so they land in every H5 file.
5.  Record *n_files* H5 files with DAQ.
6.  Stop rotation (set amplitude to zero).
7.  Optionally restore pre-run sphere parameters.

Run from the terminal::

    # single rotation rate
    python coriolis_table.py --rate 0.1 --n-files 10 --output-dir D:/data/coriolis

    # rate sweep
    python coriolis_table.py --rates 0.05 0.1 0.2 0.5 --n-files 5 --output-dir D:/data/coriolis

    # dry-run (skips rotation + recording, prints what would happen)
    python coriolis_table.py --rate 0.1 --dry-run

AO rotation registers
---------------------
Rotation is driven by FPGA AO4 and AO5 in quadrature:

    AO4: x-axis drive   →  "frequency AO4" (integer, Hz × FREQ_SCALE)
                            "Amplitude AO4" (integer, V  × AMP_SCALE)
    AO5: y-axis drive   →  "frequency AO5" (same frequency as AO4)
                            "Amplitude AO5" (same amplitude as AO4)
                            "phase offset AO5" (integer, = 90° offset)

Adjust FREQ_SCALE, AMP_SCALE, and PHASE_90 to match the FPGA VI
register conventions (check fpga_registers.py and the LabVIEW source).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent.parent   # usphere-EXPT/
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from experiments.base import Experiment


# ---------------------------------------------------------------------------
# AO register scaling constants
# Adjust these to match the FPGA VI's register conventions.
# ---------------------------------------------------------------------------

FREQ_SCALE: int = 1        # integer units per Hz  (e.g. 1000 if register is mHz)
AMP_SCALE:  int = 1        # integer units per V   (e.g. 1000 if register is mV)
PHASE_90:   int = 90       # register value for 90° phase offset on AO5


# ---------------------------------------------------------------------------
# Experiment class
# ---------------------------------------------------------------------------

class CoriolisTableExperiment(Experiment):
    """
    Single-rate or multi-rate Coriolis table measurement.

    Parameters
    ----------
    rotation_rate_hz : float
        Table rotation rate in Hz (positive = CCW, negative = CW).
    n_files : int
        Number of H5 files to record per rate.
    output_dir : str
        Directory for H5 files.
    basename : str
        Filename prefix (files written as <basename>_0.h5, _1.h5, …).
    settle_s : float
        Seconds to wait after setting rotation before recording.
    ao_amplitude_v : float
        Amplitude of AO4/AO5 drive signal (V).
    save_sphere : bool
        If True, save current FPGA parameters before run and restore after.
    dry_run : bool
        If True, print the sequence but do not send any commands.
    """

    REQUIRES = ["ctrl", "daq"]

    def __init__(
        self,
        rotation_rate_hz: float,
        n_files: int,
        output_dir: str,
        basename: str = "coriolis_table",
        settle_s: float = 30.0,
        ao_amplitude_v: float = 1.0,
        save_sphere: bool = True,
        dry_run: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.rotation_rate_hz = rotation_rate_hz
        self.n_files          = n_files
        self.output_dir       = str(output_dir)
        self.basename         = basename
        self.settle_s         = settle_s
        self.ao_amplitude_v   = ao_amplitude_v
        self.save_sphere      = save_sphere
        self.dry_run          = dry_run
        self._sphere_save_path: str | None = None

    # ------------------------------------------------------------------
    # AO rotation control
    # ------------------------------------------------------------------

    def _set_rotation(self, rate_hz: float) -> None:
        """
        Set table rotation via FPGA AO4/AO5 in quadrature.

        AO4 drives one axis, AO5 drives the orthogonal axis at 90° phase
        offset.  Both channels run at the same frequency (rotation rate)
        and amplitude.  Setting amplitude to zero stops rotation.
        """
        freq_int = int(abs(rate_hz) * FREQ_SCALE)
        amp_int  = int(self.ao_amplitude_v * AMP_SCALE) if rate_hz != 0.0 else 0

        registers = {
            "frequency AO4":   freq_int,
            "Amplitude AO4":   amp_int,
            "reset AO4":       0,
            "frequency AO5":   freq_int,
            "Amplitude AO5":   amp_int,
            "phase offset AO5": PHASE_90 if rate_hz > 0 else -PHASE_90,
            "reset AO5":       0,
        }

        label = f"{rate_hz:+.4f} Hz" if rate_hz != 0.0 else "STOPPED"
        if self.dry_run:
            print(f"  [DRY RUN] set_rotation({label})  registers: {registers}")
            return

        reply = self.ctrl.send("write_many", values=registers)
        errors = reply.get("data", {}).get("errors", {})
        if errors:
            print(f"  [WARN] rotation register write errors: {errors}")
        else:
            print(f"  rotation set to {label}")

    def _stop_rotation(self) -> None:
        self._set_rotation(0.0)

    # ------------------------------------------------------------------
    # Sphere save / restore
    # ------------------------------------------------------------------

    def _save_sphere(self) -> None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = str(Path(self.output_dir) / f"sphere_pre_{ts}.json")
        if self.dry_run:
            print(f"  [DRY RUN] save_sphere → {path}")
            self._sphere_save_path = path
            return
        reply = self.ctrl.send("save_sphere", filepath=path)
        self._sphere_save_path = reply.get("data", {}).get("filepath", path)
        print(f"  sphere saved → {self._sphere_save_path}")

    def _restore_sphere(self) -> None:
        if not self._sphere_save_path:
            return
        if self.dry_run:
            print(f"  [DRY RUN] load_sphere ← {self._sphere_save_path}")
            return
        reply = self.ctrl.send("load_sphere", filepath=self._sphere_save_path)
        errors = reply.get("data", {}).get("errors", {})
        if errors:
            print(f"  [WARN] sphere restore errors: {errors}")
        else:
            print(f"  sphere restored ← {self._sphere_save_path}")

    # ------------------------------------------------------------------
    # Single-rate recording pass
    # ------------------------------------------------------------------

    def _run_one_rate(self, rate_hz: float, file_index_offset: int = 0) -> None:
        rate_str = f"{rate_hz:+.4f}Hz".replace("+", "p").replace("-", "n").replace(".", "d")
        basename = f"{self.basename}_{rate_str}"

        print(f"\n--- rotation {rate_hz:+.4f} Hz  ({self.n_files} files → {basename}) ---")

        # 1. Set rotation
        self._set_rotation(rate_hz)

        # 2. Settle
        if self.settle_s > 0:
            print(f"  settling {self.settle_s:.0f} s …")
            if not self.dry_run:
                time.sleep(self.settle_s)

        # 3. Build experiment metadata to inject
        extra = {
            "experiment_type":  "coriolis_table",
            "rotation_rate_hz": rate_hz,
            "ao_amplitude_v":   self.ao_amplitude_v,
            "settle_s":         self.settle_s,
            "n_files":          self.n_files,
            "ts_start":         time.time(),
        }

        # 4. Inject FPGA snapshot + TIC + experiment metadata
        if not self.dry_run:
            self.inject_ctrl_state(extra=extra)
        else:
            print(f"  [DRY RUN] inject_ctrl_state + experiment metadata")

        # 5. Start recording
        if not self.dry_run:
            self.start_recording(
                n_files=self.n_files,
                output_dir=self.output_dir,
                basename=basename,
            )
            self.wait_for_recording(verbose=True)
        else:
            print(f"  [DRY RUN] start_recording(n_files={self.n_files}, basename={basename!r})")
            print(f"  [DRY RUN] wait_for_recording()")

    # ------------------------------------------------------------------
    # Experiment entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        print(f"=== Coriolis Table Experiment ===")
        print(f"  rate:       {self.rotation_rate_hz:+.4f} Hz")
        print(f"  n_files:    {self.n_files}")
        print(f"  output_dir: {self.output_dir}")
        print(f"  settle:     {self.settle_s:.0f} s")
        print(f"  dry_run:    {self.dry_run}")

        Path(self.output_dir).mkdir(parents=True, exist_ok=True)

        if self.save_sphere:
            self._save_sphere()

        self._run_one_rate(self.rotation_rate_hz)

    def cleanup(self) -> None:
        """Stop rotation and restore sphere parameters."""
        print("\n--- cleanup ---")
        self._stop_rotation()
        if self.save_sphere:
            self._restore_sphere()


# ---------------------------------------------------------------------------
# Rate-sweep wrapper
# ---------------------------------------------------------------------------

class CoriolisTableSweep:
    """
    Run CoriolisTableExperiment at each rate in *rates*.

    Parameters
    ----------
    rates : list[float]
        Rotation rates in Hz.  Passed one at a time to separate recording
        basenames.
    All other kwargs forwarded to CoriolisTableExperiment.
    """

    def __init__(self, rates: list[float], **kwargs) -> None:
        self.rates  = rates
        self.kwargs = kwargs

    def run(self) -> None:
        for i, rate in enumerate(self.rates):
            print(f"\n[sweep {i+1}/{len(self.rates)}]")
            with CoriolisTableExperiment(rotation_rate_hz=rate, **self.kwargs) as exp:
                exp.run()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Coriolis table experiment",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--rate",  type=float,
                       help="single rotation rate (Hz)")
    group.add_argument("--rates", type=float, nargs="+", metavar="HZ",
                       help="rate sweep — record at each rate in sequence")

    p.add_argument("--n-files",    type=int,   default=10,
                   help="H5 files per rate")
    p.add_argument("--output-dir", type=str,   default="data/coriolis_table",
                   help="output directory for H5 files")
    p.add_argument("--basename",   type=str,   default="coriolis_table",
                   help="H5 filename prefix")
    p.add_argument("--settle",     type=float, default=30.0,
                   help="settle time after setting rotation (s)")
    p.add_argument("--amplitude",  type=float, default=1.0,
                   help="AO4/AO5 drive amplitude (V)")
    p.add_argument("--no-save-sphere", action="store_true",
                   help="skip saving/restoring sphere parameters")
    p.add_argument("--dry-run",    action="store_true",
                   help="print sequence without sending commands")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    common = dict(
        n_files=args.n_files,
        output_dir=args.output_dir,
        basename=args.basename,
        settle_s=args.settle,
        ao_amplitude_v=args.amplitude,
        save_sphere=not args.no_save_sphere,
        dry_run=args.dry_run,
    )

    if args.rate is not None:
        with CoriolisTableExperiment(rotation_rate_hz=args.rate, **common) as exp:
            exp.run()
    else:
        CoriolisTableSweep(rates=args.rates, **common).run()


if __name__ == "__main__":
    main()
