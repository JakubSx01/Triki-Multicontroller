# Controller options — independent quality/release-readiness review

**Initial verdict: REQUEST_CHANGES.** Two reproducible Linux safety/lifecycle defects were found after the repaired specification gate.

**Resolution update (parent verification):** Q1/Q2 have been repaired, including identity-based manual-target transport blocking and fail-closed retryable uinput ownership. The parent reran the full protected display suite: **494 passed, 89 subtests passed, three hardware tests excluded**. Combined independent quality/specification regressions: **12 passed, three alternative manual-pin/cycle policy assertions explicitly excluded**; seven earlier native regression probes passed. Linux frozen build/GUI smoke exited 0. This closes the reproduced blockers; real hardware/native target-app acceptance remains unverified.

## Scope and method

Reviewed the changed GUI/settings/session/runtime/profile-mapper and Linux/Windows/macOS input/audio seams, plus the Polish README. This is an independent source review with inert executable regressions, not a real Jev service call or hardware acceptance. No paid service, installation, physical input, source edit, commit, push, or user configuration write was performed.

The supplied prior receipt reports the protected display suite passing (474 tests, 89 subtests; three hardware cases deselected). That is prior evidence, not a fresh execution by this reviewer. This review deliberately adds failure paths outside the repaired specification probes; it does not reopen the resolved manual-pin/shake policy or demand an obsolete whole-class GUI snapshot hash.

## Blocking findings

### Q1 — P1: missing playerctl allows an explicit Linux pin to leak global transport

**Locations:** `src/triki_controller/output/uinput_backend.py:245–256`; `src/triki_controller/output/mpris_volume.py:390–397`.

The new fail-closed transport branch only recognizes the literal substring `selected player unavailable`. With an explicitly selected player and no available `playerctl`, `MprisPlayerVolume.apply_transport()` instead returns `mpris: brak playerctl`. The backend then emits the global uinput transport pulse and reports the frame applied. The manual target has not been verified, so another application can receive that action.

This directly contradicts the no-substitution guidance in `README.md:228` and `README.md:234`. It also occurs in a supported installation state: the README correctly says `playerctl` is not supplied by pip (`README.md:84`). A saved manual identifier can outlive the tool's availability.

**Red regression:** `test_manual_pin_missing_playerctl_never_emits_global_transport` in the scratch module below. The MPRIS resolver is replaced with a function returning `None`; the uinput device is a recording fake.

Actual result:

```text
calls = [(1, 164, 1), (1, 164, 0)]
detail = 'uinput+mpris apply; mpris: brak playerctl; fallback uinput play_pause'
```

The calls are a fake EV_KEY/KEY_PLAYPAUSE down/up pair, not hardware output. The expected empty call list fails.

**Small fix direction:** make explicit manual selection a structured fail-closed condition, independent of English error-text matching. At minimum, when `media_player` is non-null, any failed/unavailable targeted transport must return an unsuccessful receipt without global fallback. Retain existing global fallback for Auto. Cover missing executable, discovery failure, missing player, and reappearance; do not loosen the existing unavailable-player regression.

### Q2 — P1: rejected Linux live edits can leave runtime Live while the UI says Off

**Locations:** `src/triki_controller/gui/session.py:403–455`; `src/triki_controller/runtime/emulator.py:120–121,307–313`; `src/triki_controller/output/uinput_backend.py:291–342`.

The new Linux backend correctly retains a key whose release fails and raises from `close()`. However, the non-native runtime path sets `_active = False` only *after* neutralization and close. A persistent key-up error therefore leaves runtime active/live. The settings rollback catches that failure and its cleanup retry, restores the accepted settings, and sets the displayed output mode to Off. It never disarms the Linux runtime; `cleanup_pending` is also always false for uinput because that property is native-only.

**Red regression:** `test_failed_linux_live_edit_disarms_runtime_and_retains_cleanup_owner`. An inert mouse backend starts with `key_a` held; the fake UI raises on every release. Editing the binding to `key_b` triggers the real session transaction.

Actual result:

```text
session output mode = Off
accepted bindings restored = {'mouse': {'button': 'key_a'}}
runtime.active = True
runtime.live = True
backend.closed = True
error = 'Nie udało się zastosować sterowania: release key_a: inert persistent key-up failure; cleanup: release key_a: inert persistent key-up failure'
```

The assertion that runtime is disarmed fails. The backend reference and held-key ownership currently remain retained; this is not a claim that ownership is already discarded. Nor does the closed backend silently emit subsequent frames: subsequent runtime dispatch attempts a closed backend and raises instead. The defect is the contradictory Off/Live state, continued dispatch attempts, and missing explicit cleanup-pending lifecycle. The native path already avoids this by disabling dispatch before cleanup and retaining a retryable owner.

**Small fix direction:** extend the fail-closed owned-output lifecycle to Linux uinput: disable dispatch before attempting releases, inspect unsuccessful neutralization receipts, retain a cleanup-pending backend across failures, permit explicit release retry, and prevent replacement/reactivation until cleanup succeeds. Do not simply move `_active = False` earlier without a retained pending owner, because the current non-native retry path skips cleanup for inactive runtimes. Keep accepted-settings rollback and no automatic Live rearm. Cover persistent and transient key-up failures for live edits, Stop, disconnect, profile changes, and failed-open cleanup without touching real uinput.

## Executed verification

Interpreter: `/home/jakub/.hermes/cache/scratch/triki-shell-system-venv/bin/python`.

```bash
PYTHONPATH=src:/home/jakub/.hermes/cache/scratch \
PYTHONDONTWRITEBYTECODE=1 DISPLAY=:0 \
/home/jakub/.hermes/cache/scratch/triki-shell-system-venv/bin/python \
-m pytest -q -p no:cacheprovider \
/home/jakub/.hermes/cache/scratch/triki_quality_regressions.py \
/home/jakub/.hermes/cache/scratch/triki_spec_regressions.py \
-k 'not enabled_cycle_after_manual_selection' \
--junitxml=/home/jakub/.hermes/cache/scratch/triki-quality-regressions.xml
```

**Observed: 2 failed, 10 passed, 3 deselected (0.34 s).** The failures are Q1 and Q2. The three conditional manual-cycle expectations were excluded because the resolved policy intentionally blocks shake changes under a manual pin.

The passing assertions independently cover:

- Windows and macOS key-up error strings preserve held-key ownership until a successful close retry.
- Runtime input settings and session settings snapshots are detached from caller mutations.
- GUI rejected binding edits restore accepted menu/state values.
- Missing manual targets stay visible as unavailable; the shake checkbox is disabled under manual selection and restores the stored false value on Auto.
- The media editor's collection leaves another profile's binding map unchanged.
- The six repaired unconditional specification probes: missing Windows manual target blocks global transport; rejected native live binding edit preserves configuration; native direction-only Plane accepts the default physical button; Linux manual retarget/reappearance retain the full volume range; schema defaults and direction hysteresis.

`evdev.UInput` is replaced by an assertion failure before all imports; Linux output uses recording fake devices. GUI callbacks use inert settings/list providers, with no BLE connection or config persistence.

## Documentation and non-blocking review notes

- README distinguishes platform-native keyboard/mouse output from unsupported analog HID Windows/macOS (`105–119`, `259`), including the inactive default joystick trigger in binding-only mode.
- README correctly discloses global Windows transport versus Core Audio volume targeting (`235`), GUI/quick-command support versus the legacy `emulate` settings seam (`417`), explicit-only Save (`317–320`), and lack of hardware certification (`5–7`, `501`).
- The explicit manual pin/shake policy and restoration of the stored checkbox flag agree with the tested GUI behavior (`230`).
- No additional independently demonstrated important/critical defect was found in the reviewed Windows/macOS held-key retry, settings copy, or GUI callback-rollback paths. This is not proof of platform hardware behavior.
- `ConfigForm`'s older docstring describes only axis maps/thresholds although it now includes options. The native `_MOUSE` alias now includes keyboard actions, so its name is broader than its meaning. These are minor clarity issues, not blockers or reasons for refactoring untouched code.

## Owned artifacts

- Repository report: `docs/controller-options-quality-review.md`.
- Scratch regressions: `/home/jakub/.hermes/cache/scratch/triki_quality_regressions.py` (reuses existing inert helpers from `triki_spec_regressions.py`).
- Execution receipt: `/home/jakub/.hermes/cache/scratch/triki-quality-regressions.xml`.

Only the report and new scratch artifacts were written by this reviewer. Re-run these red assertions and the protected suite after the fixes; real BLE/native-input/audio/platform acceptance remains a separate explicit opt-in activity.
