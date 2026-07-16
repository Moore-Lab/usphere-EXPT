# Session log

Running log of work sessions (human or Claude) on this checkout. **Newest entry
first.** Every session that changes the repo appends an entry before committing —
see CLAUDE.md for the protocol.

Entry template:

```
## YYYY-MM-DD — <short title>
**Focus:** one line on what the session set out to do.
**Changes:** files added/modified/deleted, and any commits pushed.
**State / handoff:** anything left in flight, known issues introduced or found,
follow-ups for the next session.
```

---

## 2026-07-16 — Analysis SR530 source reuses the Lock-In tab connection
**Focus:** Remove the double-connect confusion when calibrating the lock-in.
**Changes:** usphere-Q `dcd6853` (pushed), parent synced. The Analysis "Lock-in
(SR530 direct)" source used to open its OWN SR530Controller on the same COM port
as the Lock-In tab — impossible (serial ports are exclusive), and confusingly
redundant. Now: SR530Tab exposes `controller()`; AnalysisTab gained
`set_sr530_provider()` and `_on_start` prefers the shared controller;
`_SR530PollThread`/`SR530SerialSource` accept a `controller=` to poll snapshot()
without connect/disconnect (never closes a connection it doesn't own); charge_gui
wires the provider. The Analysis "SR530 serial port" field is now a fallback only
(blank = use Lock-In tab), with an in-UI note. Headless-verified.
**State / handoff:** Calibration workflow now: connect SR530 once in the Lock-In
tab (set phase so Y≈0, pick sensitivity) → Analysis: pick "Lock-in (SR530
direct)", set volts-per-electron (or leave for the Calibration tab's auto-cal to
fill) + optional cal drive amp → run → Calibration tab auto-cal at a known charge.
Poll rate = Analysis read cadence (distinct from the Lock-In Monitor's display
poll). If both the Lock-In Monitor and the Analysis source poll at once they
serialize on the controller's RLock (works, just shares bandwidth).

## 2026-07-16 — Control tab: arm NGE DC outputs for the session
**Focus:** Make the Control tab a turnkey automatic charge/discharge tester.
**Changes:** usphere-Q `f7e6b87` (pushed), parent synced. The ChargeController
already consumed the calibrated/normalized charge (`charge_updated`), but only
gated the flash/filament triggers — the NGE DC levels had to be enabled by hand.
Now `ChargeController.start()` arms both actuators (NGE flash-control +
filament-power outputs ON at their setpoints) and `stop()` disarms (session
on/off, DC steady, triggers gate actuation). Added `FlashLampAdapter.arm/disarm`,
a new `FilamentAdapter` (filament trigger + NGE power), and `DriveSetbackAdapter`
pass-through; charge_gui wraps the filament in FilamentAdapter. getattr-guarded
so mocks/None/photon-experiment are unaffected. Headless-verified.
**State / handoff:** Operator still sets the flash-control voltage + filament
power *levels* in the Flash Lamp / Filament tabs (and flash rate / filament
freq-width); the Control tab turns those outputs on for the session and does the
threshold logic (target ± tolerance or a rule = "turn off after crossing"). The
Photon Order experiment has the same NGE-gating gap (out of scope here) — it
drives flash only for reset, so no regression. Control tab and Experiment tab
share the charge input but use different actuator engines (bang-bang vs step
sequencer) — this is intended.

## 2026-07-16 — Sequencer 'Set electrode field' command
**Focus:** Let the sequencer raise/lower the drive field between steps (measure
high-SNR, recharge at low field so the filament doesn't eject the sphere).
**Changes:** usphere-Q `591d5c7` (pushed), parent synced. New `set_electrode`
SeqStep action (amplitude + settle); ChargeSequencer emits
`set_electrode_requested(amp)`; charge_gui applies it on the GUI thread (sets the
monitored-axis drive spinbox = source of truth, re-applies to program the AFG +
re-mirror the reference, pushes the amplitude to the charge normalization). UI
adds the action page; 'Wait' relabeled 'Wait (delay)'. Headless-verified.
**State / handoff:** Set-electrode targets the MONITORED axis drive (no axis
picker yet — easy to add). Uses the drive spinbox as the single source of truth
so it stays consistent with effective_amplitude()/normalization. Still awaiting
live commissioning on a real sphere. (User's request message was truncated at
"So I would" — implemented the clear ask; may have had more to specify.)

## 2026-07-16 — Compound charge-control command sequencer (Phase 2)
**Focus:** List-based charge/discharge cycle sequencer in the Experiment tab.
**Changes:** usphere-Q `fc7f85d` (pushed), parent synced. New `charge_sequence.py`
(SeqStep + threaded ChargeSequencer engine: each step = discharge/recharge/wait
with a signed charge-threshold stop condition |q|≤/≥ or q≤/≥, per-step timeout,
global safety charge-limit ceiling; list repeats N times, 0=until stopped);
`ChargeSequencerActuators` in wg_control_tab (resolves AFG/NGE handles on the GUI
thread in prepare(), programs controllers directly from the worker thread —
thread-safe); `sequencer_tab.py` (step editor + add/reorder/remove list + repeat
/limit/poll + Start/Stop + log). Wired in charge_gui as the "Command Sequence"
sub-tab of a new Experiment tab-group; charge feed + config persist. Headless-
validated (mock actuator + simulated charge): multi-cycle discharge/recharge hits
thresholds, timeout/safety-limit/Stop all work, config round-trips.
**State / handoff:** NOT yet run on a real sphere — live commissioning is next.
Per-step actuator amplitudes (trigger pulse Vhigh, NGE current limits) are taken
from the Electrodes/Filament tab widgets at Start, so set those up first; the
sequencer sets rate/freq/width/ctrl-level/power per step. Stop condition uses the
Phase-1 quantized live charge. Note: signed comparisons (q≤/q≥) are overshoot-safe
(monotonic); |q| band conditions rely on the poll observing the crossing (fine at
0.2 s poll vs slow real charge).

## 2026-07-16 — Live lock-in charge normalized by drive amplitude (always quanta)
**Focus:** Make the live lock-in readout report the same charge regardless of
drive amplitude (Phase 1 of the charge-diagnostics work).
**Changes:** usphere-Q `0b8156e` (pushed), parent synced. Physics verified
(X = C·q·A_drive ⇒ X/A_drive ∝ q) via a 3-agent workflow against the code +
checkQ. Implemented: lock-in calibration now records `drive_amplitude_vpp`
(charge_calibration); CalibrationTab captures the drive amplitude at cal time
and `lockin_cal_saved` carries (vpe, drive_amp, kind); AnalysisTab has a
"Cal drive amp (Vpp)" field per source and computes `charge = X/(vpe·drive_scale)`
with `drive_scale = current_drive/cal_drive` on every reading (0 cal ⇒ off,
backward compatible), plus a live normalization label; DriveSetbackAdapter now
reports the ABSOLUTE drive amplitude and exposes `effective_amplitude()`;
charge_gui pushes the live drive amplitude on the 2 s timer + immediately during
setback. Headless-verified charge constant to 1e-6 over a 100× drive range.
**State / handoff:** Uses the COMMANDED drive amplitude (2×-accuracy live
diagnostics, as the user intends — offline checkQ is the precision path).
Measured-drive demodulation from AI18–20 is a documented future refinement.
Amplitude normalization does NOT remove susceptibility/resonance drift — still
needs periodic recalibration for absolute charge. NEXT (Phase 2, user-requested):
compound charge-control command sequencer in the Experiment tab (list-based
charge/discharge cycles with per-step tweaks), modeled on the Electrodes Sweep
tab.

## 2026-07-15 — Lock-in reference now mirrors the drive's output on/off
**Focus:** Extend the reference mirror to the output state (per user request).
**Changes:** usphere-Q `46ce53a` (pushed), parent pointer synced. New
`_on_output_changed` hook on ChannelControlWidget → `notify_drive_output` on
LockInReferenceGroup: drive OFF → reference OFF; drive ON → sync + reference ON
(only when the toggled channel is the mirrored one). Drive-setback is
unaffected (it changes amplitude, never toggles output — reference stays on at
fixed amplitude while charging). Live-verified on WG1/COM4 through the real
drive-tab buttons.
**State / handoff:** No new caveats. Same as the prior entry: reference (WG1-CH2)
has no ADC; ref+mirror must be the two channels of one AFG.

## 2026-07-15 — Self-mirroring lock-in reference in the channel map
**Focus:** Make the lock-in reference (WG1-CH2 → SR530 REF IN) a user-assignable,
self-mirroring output so it can be repointed without recoding.
**Changes:** usphere-Q `e7472a6` (pushed), parent pointer synced.
`LockInReferenceGroup` in the Channel Map tab: assign reference WG/CH + the drive
WG/CH it mirrors (mirror auto-fills to opposite CH same WG, validated; names the
drive from the electrode map). One knob = reference amplitude (fixed, so the
SR530 keeps lock while the drive amplitude varies). True mirror: reads the
mirrored channel's live waveform (type + freq + duty/width/symmetry), reproduces
it on the reference at the reference amplitude, phase-locks via AFG
`sync_phases`; re-mirrors automatically when the drive is applied (new
`_on_applied` hook on ChannelControlWidget); ARB/comb warns to set manually.
Persisted as `LockInRef`. Live-verified on WG1/COM4 (square & sine mirrored at
fixed amplitude, independent of drive amplitude, auto-remirror).
**State / handoff:** The reference output (WG1-CH2) is not on an ADC, so it's
verified by AFG config readback, not the DAQ. Reference and mirror MUST be the
two channels of one AFG (phase-lock requirement) — enforced in the UI. Changing
the reference amplitude needs a Sync/Output-ON click (waveform follows the drive
automatically; amplitude is the deliberate manual knob). Lock-in charge
measurement + calibration is the next phase and can now use this reference.

## 2026-07-15 — NGE100 power supply integration + hardware rewiring
**Focus:** Adapt usphere-Q to the reorganized charge hardware (7 outputs across
3 AFG-2225 WGs + an R&S NGE103B DC supply) and integrate the power supply into
the control/GUI.
**Changes:** usphere-Q `90d8152` (pushed), parent pointer synced. Vendored
`resources/NGE100_controller` as a submodule; added `nge_supply.py` (root
wrapper, mirrors wg_flashlamp.py). New GUI: NGE connection panel (defaults
COM3), `NGEChannelMap` (flash control→CH1, filament power→CH2), `NGEControlGroup`
(V/I setpoints, Apply/On/Off, threaded readback). Flash-lamp control moved from
an AFG DC channel to the NGE; filament trigger moved WG2-CH2→WG3-CH2 and gained
an NGE power group; electrode-map defaults updated. Verified the full
**physical map against the DAQ** (empirical AFG-ch→ADC probe):
WG01=COM4 (Y=AI19 / lock-in ref), WG02=COM6 (X=AI18 / Z=AI20),
WG03=COM10 (flash trig=AI22 / filament trig=AI21), NGE=COM3 (flash ctrl=AI23 1:1
/ filament power=CH2 no-ADC). Live end-to-end: NGE voltage set via widget/adapter
lands on AI23; filament power confirmed by NGE readback. Left all instruments
off + local.
**State / handoff:** DAQ is on **PXI1Slot3** (a PXIe-6363), not Slot2 (that's the
FPGA). NGE auto-discover is timing-flaky — connect-by-port (COM3) is reliable.
The lock-in **reference** (WG1-CH2, fixed amplitude → SR530 REF IN) is wired but
its control/setup UI is deferred to the next phase (lock-in charge measurement +
calibration), which the user wants to start next. Filament power (NGE CH2) has no
ADC — verify via NGE readback only; don't fire flash/filament triggers while
setting control levels. The uncommitted `checkQ_calibration.json` in
Microsphere-Utility-Scripts (usphere-Q) is still pending an owner — untouched.

## 2026-07-14 — Drive setback while charging + lock-in reference findings
**Focus:** Reduce the electrode drive automatically while the filament charges
the sphere, restore it after, without corrupting the charge readout.
**Changes:** usphere-Q `9c92a44` (pushed): `DriveSetbackAdapter` in
wg_control_tab wraps the filament actuator (reduce drive → filament on;
filament off → restore); lock-in sources gained `set_drive_scale()` so
charge = X/(vpe·scale) stays correct while reduced (reported as
`drive_amp_scale`); ControlTab "Drive setback while charging" group
(checkbox + charging Vpp, persisted); wired in charge_gui (ChargeController
and PhotonOrderExperiment get the wrapped filament). Root pointer updated.
**State / handoff:** Hardware findings recorded here for the lab: the
AFG-2225 rear "Trigger output" is a **sweep/burst marker only** (manual p.16,
p.130) — it cannot serve as a per-cycle lock-in reference in continuous mode;
use a dedicated AFG channel at fixed amplitude into SR530 REF IN (sine
trigger wants ≥100 mVpp symmetric, ~1 Vrms recommended; edge modes want
TTL-level pulses). Reference and drive channels must be set to the same
frequency; `sync_phases()` exists in the AFG driver. The uncommitted
`checkQ_calibration.json` edit in Microsphere-Utility-Scripts is still
pending an owner.

## 2026-07-14 — One-button auto lock-in calibration (usphere-Q)
**Focus:** Replace the type-in-a-voltage lock-in calibration with a button that
samples the live lock-in and computes V/e itself.
**Changes:** usphere-Q `0c943af` (pushed): CalibrationTab gained an
"auto" group — known |charge| + polarity + Start button; samples `raw_voltage`
from the AnalysisTab stream (SR530-direct or ESP32 source), Welford mean/SEM,
stops at target SEM (default 1%, ≥100 samples) or max samples (default 10 000);
saves V/e with SR530 sensitivity/phase metadata; refuses to save on
polarity/voltage sign mismatch; result auto-fills the Analysis tab V/e field and
updates the running source (`AnalysisTab.set_volts_per_electron`,
`lockin_cal_saved` signal wired in charge_gui). Manual workflow kept. Verified
with a headless synthetic-sample test (convergence, persistence, sign guard,
cancel, config round-trip). Root pointer updated via sync script.
**State / handoff:** `resources/Microsphere-Utility-Scripts` (inside usphere-Q)
has an UNCOMMITTED edit to the reference `checkQ_calibration.json` — a fresh
file-based recalibration (f≈99.945 Hz, 65536 samples) from the lab / a parallel
session. Left untouched; needs an owner to commit or move to a local cal file
per the per-sphere policy. The diverged
`Inertial-Sensing/microsphere_utility_scripts` from the previous entry is still
pending.

## 2026-07-14 — SR530 update: real submodule, API adaptation, sync fix
**Focus:** Pull the rewritten SR530 driver (protocol fixes + CLI, SR530_controller
`27cc1b3`) into usphere-Q and make everything that consumes it work.
**Changes:** In usphere-Q (`86433fa`, pushed): converted `resources/SR530_controller`
from accidentally-vendored files into a real submodule pinned to `27cc1b3`; removed
orphan gitlinks `resources/usphere-DAQ` / `resources/usphere-FPGA` (empty stubs that
made `git submodule status` fatal); adapted `charge_analysis.py` to the new
`snapshot()` keys (`x/y/r` now volts, `x_v/y_v/r_v` gone) and `charge_gui.py` to the
retired AdvancedTab (its absence silently disabled the whole Lock-In tab); preserved
the vendored-only user guide as `docs/SR530_USER_GUIDE.md`. In usphere-EXPT
(`68b432d`): `sync_submodules.py` now enumerates from `.gitmodules` (immune to
orphan gitlinks) and warns on index/.gitmodules mismatches. Ran
`sync_submodules.py --commit --push` — pointer commits pushed at all levels
(root `7ba1de3`).
**State / handoff:** New driver defaults: 19200 baud, no parity, 2 stop bits,
COM11, `W 0` fast readback — the physical SR530 DIP switches must match. Two
pre-existing issues surfaced by the sync, not fixed: (1)
`usphere-DAQ/analysis/Inertial-Sensing` `.gitmodules` lists `coriolis` but its files
are vendored (same trap as SR530 had); (2)
`.../Inertial-Sensing/microsphere_utility_scripts` has local commits diverged from
origin/main — needs a manual rebase/merge decision. usphere-CTRL still has
untracked in-flight content from another session — untouched.

## 2026-07-14 — Session log + CLAUDE.md for parallel-session coordination
**Focus:** Full repo read-through, then set up coordination files so parallel
Claude sessions keep the repo and each other up to date.
**Changes:** Added `SESSION_LOG.md` (this file), `CLAUDE.md` (session protocol +
repo rules), and `.gitignore` (`__pycache__/`). Committed the previously
untracked `ARCHITECTURE.md` and the shortcut/icon work from the parallel
session (see entry below). Committed and pushed on `unified-framework`.
**State / handoff:** `.vscode/` left untracked (machine-local editor config).
The `usphere-CTRL` submodule has untracked content inside it — left alone,
belongs to whichever session is working there. Known code warts found during
the read-through are listed at the bottom of CLAUDE.md.

## 2026-07-14 — Desktop shortcut + application icon (parallel session)
**Focus:** One-click launch of the unified GUI from the Windows desktop.
**Changes:** `make_icon.py` (renders a 512×512 levitated-microsphere icon and
packs a multi-resolution `.ico`), `resources/icons/microsphere.ico` + `.png`
preview, and `create_shortcut.py` updated to point the "usphere EXPT.lnk"
desktop shortcut at `expt_gui.py` with that icon (python resolution:
`./.venv` → `../usphere-FPGA/.venv` → current interpreter, prefers
`pythonw.exe`).
**State / handoff:** Files were left untracked; committed by the session above.
Re-run `python create_shortcut.py` (from the shared venv) after moving the
checkout or regenerating the icon.
