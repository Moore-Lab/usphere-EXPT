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

## 2026-07-18 — Charge-Q: SR530 auto-range, start-charge-monitor, bounded ramp
**Focus:** Auto-range the lock-in, a one-click "start charge monitor", bounded
filament ramp, and more defaults.
**Changes:** usphere-Q `2a6a263` + `9beb7c7` (pushed), parent pointer updated
(hand-staged usphere-Q only). (1) Filament ramp now STOPS at max width
(PulseRampRunner "maxed" reason) — start==max fires one pulse then off; the
control loop reports "reached max width — target not reached". (2) Analysis
defaults: axis Y, source Lock-in (SR530 direct). Control-tab flash control
voltage 4 V; filament NGE 5 V / 3 A. (3) `AutoRanger` (charge_analysis.py): steps
SR530 sensitivity one index at a time (more sensitive on headroom, less on
overload) with a settle window, on the poll thread (off the GUI thread).
Continuous toggle + one-shot button in the Analysis tab; a one-shot also runs
whenever the drive amplitude changes (setback park/restore during flash / ramp
filament / go to target) and from the macro. Grayed "Range" readout updates from
the stream. (4) "▶ Start charge monitor" (Analysis tab) = connect-all + drive Y
100 Hz/8 Vpp + start lock-in + auto-range. Verified (test_autorange, full suite
15/15).
**State / handoff:** The live grayed range readout + auto-range controls live in
the Analysis tab (not the SR530 Parameters tab, which still reads the range into
its combo on connect) — movable if you want it in the Lock-In tab. Auto-range
uses r_frac hysteresis (0.15/0.9) + a 0.5 s settle; tune if it hunts. The
start-monitor macro uses a fixed 5 s delay for the async connects before driving
Y / starting the lock-in.

## 2026-07-18 — Charge-Q setup: connect-all, defaults, calibration load, flash off-thread
**Focus:** Startup/UX batch for the charge GUI + move the flash lamp off the
GUI thread like the filament.
**Changes:** usphere-Q `79c1bc1` (pushed), parent pointer updated (hand-staged
usphere-Q only). Connections tab: "Connect to all" button (WG1/2/3 + NGE, then
via ChargeWidget the SR530 lock-in + a delayed reference sync). Defaults:
x/y/z drive amp 8 Vpp, lock-in reference amp 8 Vpp, flash 200 Hz / 4 ms,
flash-control NGE voltage 4 V (new NGEControlGroup `default_voltage_v`).
Calibration: `make_lockin_cal` now records `known_charge`; new
`most_recent_lockin_cal()`; the most recent lock-in cal auto-loads into
Analysis (V/e + cal drive amp) when the SR530 connects; a dropdown + "Load
calibration" button loads a chosen cal (V/e + cal drive amp → Analysis, known
charge/polarity → charge inputs). Cal drive amp `drive_amplitude_vpp` was
already in the schema/file (10µm sphere = 8 Vpp, in the vendored
checkQ_calibration.json — not committed by me). Flash lamp off the GUI thread:
`FlashLampAdapter` enable/disable run on a background `_AfgActionQueue` (like
the filament pulser); `set_flash_rate` no longer does a blocking apply (enable
applies). Verified headless (14/14 incl. new test_flash_pulser + cal auto-load).
**State / handoff:** "Known charge in Analysis" — Analysis has no known-charge
field, so a loaded cal's known charge goes to the Calibration charge inputs;
V/e + cal drive amp go to Analysis. Reference "sync on connection" is a
best-effort delayed sync (WG connects are async); the drive-apply/output
auto-mirror is the real path and already worked.

## 2026-07-18 — Filament firing moved to a background thread (fix GUI freeze)
**Focus:** The Control tab froze/crashed while ramping the filament.
**Changes:** usphere-Q `d780512` (pushed), parent pointer updated (hand-staged
usphere-Q only). Root cause: each pulse-wait-read step reprogrammed the whole
AFG waveform on the GUI thread — `setup_pulse`'s apply is a *synced* serial
write (~230 ms) + period/width + output toggles ≈ 0.6 s of blocking I/O per step
inside `on_charge_update`, contended by the 2 s actuator-sync timer. The
algorithm was fine; the firing was the problem (user confirmed pulse→wait→read
is a hard constraint — a continuous train gives noisy reads). Fix: keep the
algorithm, move firing off the GUI thread. New `_FilamentPulser` (QThread) owns
the filament AFG serial I/O; `FilamentAdapter.fire_pulse/pulse_off` capture the
handle on the GUI thread and enqueue (return in ~1 ms vs ~600 ms). Set the pulse
up ONCE per channel, then per step change only the WIDTH (one cheap
`SOUR:PULS:WIDT`, only when changed) + toggle output — no per-step reprogram.
Pulser coalesces backlog; disable/off ordered through it (a queued fire can't
re-enable after stop); `shutdown()` on GUI close. Manual FilamentRampWidget uses
it too. Verified (test_filament_pulser); full suite 13/13.
**State / handoff:** Firing logic unchanged — still 1 mHz carrier + output-on =
one pulse; **bench-verify output-on restarts the pulse at phase 0**. Sequencer
recharge already fires off the GUI thread (never froze) but still full-reprograms
per pulse (slower, not a crash) — could adopt the same set_pulse_width later.

## 2026-07-18 — Control tab redesign: flash/filament/target, direction-based
**Focus:** The Control tab was hard to use. Strip it to basic flash/filament
usage + a target/tolerance auto-control, all synced to the SR530 read cycle.
**Changes:** usphere-Q `ea4417b` (pushed), parent pointer updated (hand-staged
usphere-Q only; siblings hold other sessions' work). ChargeController rewritten
direction-based with a policy (auto|flash|filament): flash raises + (continuous,
evaluated each read), filament lowers − (pulse-wait-read ramp), auto picks by
direction to a target ± tolerance; relative "change by Δ" targets; safety
timeout (default 10 min) enforced by an independent QTimer watchdog; cancel();
`stopped` signal; per-tool Δq diagnostics (RampCycle.device). Drive setback now
applies to BOTH tools via a shared object (set_drive_setback) and gained
fire_pulse/pulse_off/park/restore (also fixes the pulse ramp under the
setback-wrapped filament — a latent bug from the prior commit). ControlTab
rebuilt (Flash/Filament/Target panels, gray status, shared Cancel, cycle logs);
rules/lists/old timing removed. q_server.py/q_cli.py: dropped removed
set_timing/add_rule/clear_rules, added set_policy/set_timeout/set_flash_params.
Ran a 4-dimension adversarial review workflow (parallel agents); its 3 confirmed
findings (timeout watchdog, filament overshoot false-success, q_server
regression) are all fixed. Headless-verified: 12/12 suite green.
**State / handoff:** Still needs the same bench check as the prior commit — the
1 mHz single-pulse firing assumes the AFG restarts the pulse at phase 0 on
output-on. Bang-bang flash/filament in auto can oscillate if the tolerance is
narrower than one filament pulse's charge; widen tolerance or start-width.

## 2026-07-17 — Filament pulse-wait-read ramp (shared Control + sequencer core)
**Focus:** The filament runs away and makes the lock-in noisy while on, so the
old continuous freq/width ramp was hard to control. Replace it with a
pulse→wait→read→increment loop that reads only when the filament is off.
**Changes:** usphere-Q `b6a18d4` (pushed), parent pointer updated (hand-staged
usphere-Q only — siblings usphere-CTRL/.vscode hold other sessions' uncommitted
work, so I did NOT run the recursive sync). `PulseRampRunner` + slimmed
`FilamentRamp{enabled,start_width_ms,increment_ms,max_width_ms,timeout_cycles}`
in charge_control.py: fire ONE pulse of width W, wait N clean read cycles
(filament off), read charge, evaluate the stop condition, else increment width
and refire. Frequency ramp dropped. Single-pulse firing via a 1 mHz carrier
(`fire_single_pulse`/`FilamentAdapter.fire_pulse`/`ChargeSequencerActuators
.fire_filament_pulse`): output-on fires one hardware-timed pulse, off long
before the ~1000 s-away next one — no burst mode needed. Shared core loop:
ChargeController HEAT (`_run_pulse_ramp`, suspends rules/at-target while active)
and the sequencer recharge (`_run_recharge`; SeqStep gains fil_start_width_ms/
increment/max/timeout_cycles, legacy freq/width kept for old configs). Grayed
`CycleLog` diagnostics (width + Δq/read) for filament + flash in the Control
tab. Removed old mode-based `FilamentRamp`/`_execute_heat_ramp`. Headless-
verified (pulse-ramp state machine, ChargeController, sequencer engine + tab).
**State / handoff:** The 1 mHz single-pulse firing assumes the AFG restarts the
pulse waveform at phase 0 on output-on — **verify on the bench**; if it
free-runs the phase, the pulse won't fire and we need an explicit phase reset.
Next: Control-tab UX overhaul (basic flash/filament runners + target/tolerance
+ T-min safety timeout, strip rules) — in progress this session.

## 2026-07-16 — Lock-in calibration accepts a signed V/e (negative is valid)
**Focus:** Fix a spurious "polarity/phase opposite sign" error when calibrating.
**Changes:** usphere-Q `67a621d` (pushed), parent synced. The lock-in X sign vs
charge polarity is set by the arbitrary SR530 phase, so a positive charge can
give a negative X → a valid NEGATIVE volts-per-electron. Bug: sources treated
`vpe>0` as the calibrated condition (negative silently fell back to raw voltage),
and the auto-cal rejected opposite-sign results. Fix: `calibrated = vpe!=0 and
|vpe|!=1.0` (1.0 stays the uncalibrated sentinel); `charge = X/(vpe*scale)` is
already correct for signed vpe; polarity now follows the computed charge's sign;
removed the auto-cal sign-mismatch guard; tooltips note the signed value.
Headless-verified (new test_signed_vpe).
**State / handoff:** No caveats. A negative V/e in the Analysis field is expected
and correct — it just records which way the SR530 phase was set.

## 2026-07-16 — Filament ramp (gentle heating caught at the threshold)
**Focus:** Filament runs away (same settings gave ~100 charges before, ~10000
now; threshold drifts daily). Ramp gently so the loop catches the onset.
**Changes:** usphere-Q `8a4c4d8` (pushed), parent synced. `FilamentRamp`
(charge_control): mode off|freq|width — ramp trigger frequency (fixed width) or
pulse width (fixed freq) from start by increment up to a maximum; step_interval_s
throttles the advance (0 = every poll), charge still checked every poll.
ChargeController `set_filament_ramp()` + `_execute_heat_ramp` (runs every poll,
advances, keeps the filament pulsing via new `FilamentAdapter.set_pulse` which
keeps the drive-setback park engaged; at-target now actively stops + resets the
ramp; ramp steps skip the max-consecutive safety; holds at max if unreachable).
Reusable `FilamentRampConfig` editor: Control tab (in-loop, applied on Start +
"Apply ramp") and Filament tab `FilamentRampWidget` (manual out-of-loop runner).
Configs persist. Headless-verified.
**State / handoff:** SSR min pulse ~5 ms — set fixed/start widths ≥5 ms. Ramp
rate = increment × poll rate (or throttled by step interval); tune increment
small so the onset is caught before runaway. At-target stop is the catch; if the
target is never reached the ramp holds at max and pulses until you Stop (no
auto-timeout yet — possible follow-up). NOT yet run on a real sphere.

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
