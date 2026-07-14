# CLAUDE.md — usphere-EXPT

Parent repo for the Yale levitated-microsphere experiment. Three submodules
(usphere-CTRL = FPGA feedback + hardware/trapping automation, usphere-DAQ =
NI PXIe-6363 → HDF5, usphere-Q = charge measurement/control) glued together by
a shared ZMQ protocol, `modules.yaml`, a unified GUI, and experiment scripts.
Read `ARCHITECTURE.md` for the full map before making structural changes.

## Parallel sessions — keep each other up to date

Several Claude sessions (and the human) may work in **this same working tree**
concurrently. Rules:

1. **At session start:** run `git status` and `git log --oneline -5`, and read
   the top entries of `SESSION_LOG.md` to learn what other sessions did or
   left in flight.
2. **Untracked or modified files you didn't create probably belong to another
   live session.** Don't revert, delete, overwrite, or commit them unless the
   user says that work is finished.
3. **Before committing:** append an entry to `SESSION_LOG.md` (template at the
   top of that file) describing focus, changes, and handoff state.
4. **Commit only the files your session touched**, with a descriptive message.
   Then `git pull --rebase` and `git push` promptly so other sessions see your
   work. Branch is `unified-framework` (parent and all submodules).
5. **Submodule pointers:** update them with `python sync_submodules.py
   --commit --push` (recurses into nested submodules), not by hand-staging —
   and only when the submodule work is actually committed and pushed.

## Repo rules

- **`zmq_base.py` is a byte-identical 4-way copy** (this repo is canonical;
  copies in usphere-CTRL/DAQ/Q). If you edit it, copy it to all four and say
  so in the commit message.
- **FPGA register names are sacred** — they must byte-match the LabVIEW
  bitfile, including leading spaces (`' ig Z'`) and typos
  (`'X_emergency_threshould'`, `'accurrm reset z2'`). Never "fix" them.
- **Never commit runtime state:** `session_state.json`,
  `*_session_log.jsonl`, `usphere-CTRL/fpga/ipc/*`, `__pycache__/`
  (gitignored), data/recording output dirs.
- **Docs lag the code — trust code.** Known-stale: DAQ_CORE/SETUP/README H5
  sections (real schema = `usphere-DAQ/daq_h5.py`, v3), usphere-Q
  `memory_for_new_AI.md` (wrong instruments, WG2/WG3 swapped),
  `usphere-trapping-protocol.md` Stage 5 (code steps the TENMA PSU, not AWG
  amplitude), FPGA_CORE.md arb handshake. Update docs when you change the
  code they describe.
- **Environment:** shared venv at `../usphere-FPGA/.venv` (see
  `.vscode/settings.json`, `create_shortcut.py`). Bare `python` on PATH is
  the broken Microsoft-Store stub — use the venv interpreter or `py`.
  Everything degrades to simulation when nifpga/nidaqmx are missing, so code
  can be exercised off the lab machine.

## Known warts (don't trip over these)

- q_server's `connect_flashlamp`/`connect_filament` ZMQ commands predate the
  AFG-2225 rewrite and raise TypeError; actuators are wired through the GUI.
- The unified GUI and QServer hold two *separate* ChargeController instances.
- `experiments/coriolis_table.py` FREQ_SCALE/AMP_SCALE/PHASE_90 are unverified
  placeholders vs the FPGA VI conventions.
- `openh5.get_data()` (Microsphere-Utility-Scripts) mis-scales schema-v2
  float files ~3052×; H5 readers must branch on dtype.
- Vacuum safety interlocks live only in fpga_gui — raw ZMQ
  `tic_command`/`module_command` bypass them.
- Microsphere-Utility-Scripts is vendored in 3+ drifted copies; coordinate
  conventions differ between analysis docs.
