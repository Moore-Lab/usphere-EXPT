# usphere-EXPT Architecture

How this codebase is organised and why. The system traps and characterises a charged microsphere in optical feedback; the codebase exists to make that experiment runnable both by a human at a GUI and by an autonomous agent through a CLI, against the same backend.

## Repository layout

`usphere-EXPT` is the parent repo. Three submodules carry the bulk of the instrument code, each owning a piece of the experiment:

- **usphere-CTRL** — feedback control, FPGA, vacuum / valve / motor instruments, automation procedures
- **usphere-DAQ** — high-rate analog input recording (NI PXIe-6363) and per-file metadata capture
- **usphere-Q** — charge state measurement and tracking

The parent repo holds the glue: `expt_gui.py`, `expt_client.py`, the module registry (`modules.yaml`), the shared ZMQ protocol (`zmq_base.py`), and experiment scripts (`experiments/`).

## Stitching instruments together

Every instrument in the system is added through a small, fixed contract — no instrument knows about any other.

**In CTRL: modules and procedures.** Hardware modules live in `usphere-CTRL/modules/` and subclass a common base (`mod_edwards_tic`, `mod_butterfly_valve`, `mod_keysight_awg`, `mod_dropper_stage`, …). They expose a uniform interface for connect / read / write / teardown. Procedures (`usphere-CTRL/procedures/`) are higher-level: each procedure module exposes a `Procedure` class subclassing `ControlProcedure`, declares which modules it `REQUIRES`, and is given a `FPGAFacade` after loading. The facade is a thin interface to the live FPGA controller — procedures never import the controller directly, which keeps them testable in isolation with a mock.

**In DAQ: plugin registry.** `daq_core.py` discovers modules listed in `_PLUGIN_MODULES` at import time. Each plugin exposes `MODULE_NAME`, `DEFAULTS`, and `read()`; if `read()` raises, defaults are substituted so a missing device never blocks a file from being written. New devices = new plugin module + one line in the registry.

**At the top level: modules.yaml.** Each major service (CTRL, DAQ, Q) runs as a ZMQ server. `modules.yaml` lists them and `expt_client.py` exposes them as attributes (`expt.ctrl`, `expt.daq`, `expt.q`). Adding a new service is a single yaml entry.

## Control paths

The FPGA runs the inner 100 kHz feedback loop and is the only realtime element. Everything else is host-side Python orchestrating it.

- **Inner loop (FPGA)**: PID + filters per axis, executed in hardware.
- **Host control (CTRL)**: parameter writes, ramps, filter coefficient computation, mode switching. `FPGAController` in `fpga/core.py` is the only thing that talks to nifpga; procedures and the GUI go through `FPGAFacade`.
- **Cross-process control (ZMQ)**: `ctrl_server.py` exposes CTRL state (FPGA snapshot, TIC pressures) to other processes. DAQ subscribes through `daq_ctrl_tic` rather than opening the TIC serial port itself — the device has a single owner.
- **Data path (DAQ)**: streams analog input to HDF5. The recorder accepts injected metadata via `inject_module_data()` so any caller (coordinator script, ctrl_server, q_server) can attach the current FPGA register snapshot, pressures, or charge state to every file written.

This layering means automation can be inserted at any level: write a single FPGA register, run a procedure, or call a service over ZMQ.

## Automation

Automation lives where its dependencies live:

- **Procedures** (CTRL): sequence steps that operate on the FPGA + hardware modules. Each gets `on_fpga_update(state)` called every monitor cycle for live polling (trap detection, pressure thresholds). Sphere-caught events are fanned out through `add_sphere_caught_callback()` so any subscriber can react.
- **DAQ plugins**: analysis that runs on every recorded file (`on_file_written`).
- **Experiment scripts** (`experiments/`): top-level orchestration that issues commands across CTRL, DAQ, and Q together. These are the scripts a human writes once and runs many times; an autonomous agent runs them with parameter sweeps.

## Parallel front-ends: GUI and CLI

The same backend has two front-ends, deliberately:

**GUI (`expt_gui.py`, `fpga_gui.py`, per-module GUIs)** — for humans during setup, alignment, debugging. PyQt widgets bound directly to the controller. Procedures are loaded as tabs; their `create_widget()` returns the UI.

**CLI (`expt_client.py`, `ctrl_cli.py`, `daq_cli.py`)** — for scripted use and for agentic AI driving closed-loop tests. `ExptClient` gives attribute-style access to every registered module's ZMQ client:

```python
expt.ctrl.send("snapshot")
expt.daq.send("start_recording", n_files=5)
expt.q.send("get_charge")
expt.ctrl.subscribe(lambda msg: print(msg["data"]))
```

Both paths hit the same `FPGAController`, the same `DAQRecorder`, the same procedure code. Anything tested through the GUI works from the CLI without modification, and vice versa. This is what makes the system usable by an LLM-driven agent: it can read state, write parameters, start recordings, and wait for events through one consistent API, with no privileged GUI dependencies.

## Closed-loop testing with agents

The combination of (a) ZMQ services, (b) injected metadata in every HDF5 file, and (c) a uniform `ExptClient` lets an agent run a full closed-loop experiment:

1. Subscribe to `expt.ctrl` events (sphere-caught, pressure thresholds).
2. Issue procedure commands (catch sphere, ramp pressure, set filter parameters).
3. Trigger DAQ recordings with current parameters auto-attached as metadata.
4. Read recorded files back, analyse, decide the next step.
5. Loop.

No part of the loop requires a human at a screen; every action available in the GUI has a CLI equivalent.

## Conventions worth knowing

- **Single owner per device.** If a device has serial state (TIC, valves), one process opens it and others subscribe via ZMQ. Stops port-locking races.
- **Facade for testability.** Anything that drives hardware sits behind a small interface (e.g. `FPGAFacade`); production code uses the live version, tests use a mock.
- **Plugin discovery beats explicit wiring.** Modules and plugins are picked up from directories / registries. Adding hardware is additive, not invasive.
- **HDF5 is the system-of-record.** Live state worth recording goes into the file via `inject_module_data()` — there is no separate "settings" log to keep in sync.
- **Bitfile is authoritative for register names.** Anything talking to the FPGA must match register names in the LabVIEW `.lvbitx` exactly (whitespace included); the Python register table is verified against it.
