"""
experiments/base.py  —  usphere-EXPT experiment base class

All experiment scripts subclass Experiment.  The base class handles:

  - Connecting to the required modules via ZMQ (ctrl, daq, q, …)
  - Injecting FPGA register snapshots and TIC readings into every H5 file
  - A uniform wait-for-recording loop with timeout and Ctrl-C handling
  - Context manager / cleanup pattern

Subclass pattern::

    class MyExperiment(Experiment):
        REQUIRES = ["ctrl", "daq"]           # modules that must be online

        def run(self):
            self.inject_ctrl_state()         # FPGA + TIC → H5 attrs
            self.start_recording(n_files=5, basename="my_run")
            self.wait_for_recording()

    if __name__ == "__main__":
        with MyExperiment() as exp:
            exp.run()
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

_HERE = Path(__file__).parent.parent          # usphere-EXPT/
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from expt_client import ExptClient, ModuleClient


class Experiment:
    """
    Base class for usphere experiment scripts.

    Parameters
    ----------
    client : ExptClient, optional
        Pre-built client.  When None a fresh one is created from
        modules.yaml (default).
    registry : path-like, optional
        Path to an alternative modules.yaml.
    """

    REQUIRES: list[str] = []   # subclass sets this; checked on __init__

    def __init__(
        self,
        client: ExptClient | None = None,
        registry: str | Path | None = None,
    ) -> None:
        if client is not None:
            self._client = client
        elif registry is not None:
            self._client = ExptClient(registry_path=registry)
        else:
            self._client = ExptClient()

        # Check required modules are reachable
        missing = [m for m in self.REQUIRES if m not in self._client.available()]
        if missing:
            raise RuntimeError(
                f"Required modules not in registry: {missing}. "
                f"Available: {self._client.available()}"
            )

        offline = [m for m in self.REQUIRES if not self._client[m].ping()]
        if offline:
            raise RuntimeError(
                f"Required modules are offline: {offline}. "
                "Start the module servers before running this experiment."
            )

    # ------------------------------------------------------------------
    # Module access shortcuts
    # ------------------------------------------------------------------

    @property
    def ctrl(self) -> ModuleClient:
        return self._client["ctrl"]

    @property
    def daq(self) -> ModuleClient:
        return self._client["daq"]

    @property
    def q(self) -> ModuleClient:
        return self._client["q"]

    def module(self, name: str) -> ModuleClient:
        return self._client[name]

    # ------------------------------------------------------------------
    # FPGA / TIC helpers (ctrl → daq injection)
    # ------------------------------------------------------------------

    def snapshot_ctrl(self) -> dict:
        """Return the full FPGA register snapshot dict from ctrl."""
        reply = self.ctrl.send("snapshot")
        if reply.get("status") != "ok":
            raise RuntimeError(f"snapshot failed: {reply.get('message')}")
        return reply["data"]

    def get_tic(self) -> dict:
        """Return the latest cached TIC readings from ctrl."""
        reply = self.ctrl.send("get_tic")
        return reply.get("data", {})

    def inject_ctrl_state(self, extra: dict | None = None) -> None:
        """
        Push FPGA register snapshot + TIC readings into daq so they are
        written as module datasets in every subsequent H5 file.

        Parameters
        ----------
        extra : dict, optional
            Additional key→value metadata injected under the module name
            "experiment" (e.g. rotation rate, sequence step number).
        """
        # FPGA registers → "CTRL_FPGA" dataset in H5
        try:
            snap = self.snapshot_ctrl()
            regs = snap.get("registers", {})
            if regs:
                self.daq.send("inject", module_name="CTRL_FPGA", data=regs)
        except Exception as exc:
            print(f"[WARN] FPGA snapshot failed: {exc}")

        # TIC readings → "CTRL_TIC" dataset in H5
        try:
            tic = self.get_tic()
            if tic:
                self.daq.send("inject", module_name="CTRL_TIC", data=tic)
        except Exception as exc:
            print(f"[WARN] TIC reading failed: {exc}")

        # Optional experiment-level metadata → "experiment" dataset
        if extra:
            self.daq.send("inject", module_name="experiment", data=extra)

    def inject_charge_state(self) -> None:
        """Push current charge reading from q into daq H5 attrs."""
        try:
            reply = self.q.send("get_charge")
            data = reply.get("data", {})
            if data:
                self.daq.send("inject", module_name="CHARGE", data=data)
        except Exception as exc:
            print(f"[WARN] Charge state injection failed: {exc}")

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def start_recording(self, **kwargs) -> None:
        """Start DAQ recording. All kwargs forwarded to DAQConfig fields."""
        reply = self.daq.send("start_recording", **kwargs)
        if reply.get("status") != "ok":
            raise RuntimeError(f"start_recording failed: {reply.get('message')}")

    def stop_recording(self) -> None:
        """Stop DAQ recording."""
        self.daq.send("stop_recording")

    def wait_for_recording(
        self,
        poll_s: float = 2.0,
        timeout_s: float | None = None,
        verbose: bool = True,
    ) -> None:
        """
        Block until the DAQ recorder finishes or is stopped.

        Parameters
        ----------
        poll_s    : seconds between status polls
        timeout_s : maximum wait time (None = unlimited)
        verbose   : print file-count progress
        """
        t_start = time.monotonic()
        last_index = -1

        try:
            while True:
                reply = self.daq.send("get_status")
                state = reply.get("data", {})
                recording = state.get("recording", False)
                idx = state.get("file_index", 0)
                n = state.get("n_files", 0)

                if verbose and idx != last_index:
                    print(f"  [{time.strftime('%H:%M:%S')}] file {idx}/{n or '?'}")
                    last_index = idx

                if not recording:
                    break

                if timeout_s is not None:
                    if time.monotonic() - t_start > timeout_s:
                        print("[WARN] wait_for_recording timeout — stopping")
                        self.stop_recording()
                        break

                time.sleep(poll_s)

        except KeyboardInterrupt:
            print("\n[KeyboardInterrupt] stopping recording …")
            self.stop_recording()
            raise

    # ------------------------------------------------------------------
    # Subclass interface
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Override in subclass to implement the experiment sequence."""
        raise NotImplementedError

    def cleanup(self) -> None:
        """Called on exit (normal or exception). Override for hardware cleanup."""
        pass

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> "Experiment":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            self.cleanup()
        except Exception as exc:
            print(f"[WARN] cleanup error: {exc}")
        self._client.close()
        return False   # do not suppress exceptions
