# Controller bindings / media selector — independent specification review

## Initial verdict: BLOCKED (three demonstrated integration gaps)

**Resolution update:** B1–B3 were subsequently repaired and independently reproduced green by the parent. Current acceptance: 494 project tests +89 subtests passed (three hardware tests excluded), all six unconditional/positive scratch specification probes passed, and seven earlier native regressions passed. Three alternative-policy C1 assertions were excluded explicitly: the chosen behavior is manual pinning blocks shake, now shown by a disabled checkbox and visible GUI explanation. C2 keyboard-only legacy trigger is inactive on Windows/macOS; explicit mouse/key actions retain their normal dispatch/release. Final code-quality review and native builds/publication remain separate gates.

Review is against `docs/controller-options-plan.md:3–19` and the delegated acceptance criteria. Product source was read, not edited. No providers/Jev, installation, real input/audio emission, BLE connection, settings-file write, commit, push or release was performed. OS boundaries were replaced with inert adapters; every test harness globally replaces `evdev.UInput` with an assertion failure.

### Independently executed receipts

- Six new repository test modules: **103 passed** in 5.36 s (`test_control_bindings`, `test_control_settings`, `test_output_bindings`, `test_media_selection`, `test_control_options_gui`, `test_control_runtime`). No cache provider; three named live-UInput cases explicitly excluded.
- Independent scratch specification probes: **7 failed, 2 passed** in 0.08 s. These nine cases cover five findings; three failures are one parametrized cycle-policy finding. The cycle-policy and native-plane cases below are separated from unconditional blockers rather than treated as proven release-critical requirements.
- Independent real-Tk visibility probe reproduced the blank Multimedia screenshot, then demonstrated both delayed tab selection and an initially selected media profile render the controls. No settings written and no native output opened.
- Parent's full-suite receipt was supplied as context, not independently repeated here and not counted as this review's own result.

Reproduction environment:

```sh
cd /home/jakub/Desktop/Projekty/Triki-Multicontroller
PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 DISPLAY=:0 \
  /home/jakub/.hermes/cache/scratch/triki-shell-system-venv/bin/python \
  /home/jakub/.hermes/cache/scratch/triki_spec_regressions.py
```

The scratch test file contains complete inert adapters and exact reproductions. Its failures are intentional specification assertions, not fabricated output.

## Blocking findings

### B1 — Windows emits global transport when the explicitly selected player is missing

- Source: `src/triki_controller/output/windows_backend.py:154–163`; `src/triki_controller/output/windows_audio.py:108–116`.
- Requirement: an absent manually selected target must fail closed, not control a different player. Existing Windows global-transport limitations do not justify emitting a transport event when the explicit target is absent.
- Reproduce: create a Windows backend with inert `WindowsAudio` sessions A/B and an inert input adapter; open media with `media_player='missing'`; apply a frame containing only `play_pause`.
- Actual: input log is `[('global', 'play_pause')]`; receipt says `Windows SendInput/Core Audio apply` and is successful. No selected-player existence check occurs on this branch.
- Expected: no global transport emission for an unavailable explicit target, with a clear failed/error receipt. Automatic mode may retain its existing platform-dependent global transport behavior.
- Test: `test_windows_missing_manual_player_must_not_emit_global_transport`.

### B2 — Rejected live binding changes still replace session settings; GUI rollback then lies

- Source: `src/triki_controller/runtime/emulator.py:61–74`; `src/triki_controller/gui/session.py:397–410`; `src/triki_controller/gui/control_options.py:128–141`.
- Requirement: live binding edits must have coherent transaction/ownership semantics; an editor rejecting a candidate must not show the old mapping while the session contains the new rejected mapping.
- Reproduce: activate native Windows steering with only `left -> key_a`; call `session.apply_settings` with the last custom mapping removed.
- Actual: reactivation correctly fails because default native analog steering is unsupported. However, `session.current_settings().control_bindings` is already `{}` instead of the prior `{'steering': {'left': 'key_a'}}`. The returned error is `Nie udało się zastosować sterowania: Windows virtual gamepad/steering unavailable: requires a virtual HID driver`. The options editor rolls its local menus back to the old value on that error, producing a UI/session divergence. A later Save can persist the rejected candidate.
- Expected: retain/reconcile the previous settings on rejected edits, or explicitly commit and display the candidate with output Off. Do not silently retain a candidate while visually reverting it. Keeping output Off on unsupported native activation is correct; this finding does not require reopening an unsupported driverless analog mode.
- Test: `test_rejected_live_binding_edit_keeps_previous_settings`.

### B3 — Linux missing-target recovery loses full 0–100% volume range

- Source: `src/triki_controller/output/mpris_volume.py:288–302, 446–454`; `src/triki_controller/output/uinput_backend.py:101–102`; `src/triki_controller/runtime/emulator.py:107–109, 352–360`.
- Requirement: missing manual targets must remain pinned; when available, preserve a read-only first frame and the complete volume range.
- Reproduce: pin a currently unavailable Linux player, arm the mapper at its default 50% level, and feed a neutral frame. Make the pinned player available at actual volume 20%; feed another neutral frame, then repeated accepted 10-degree turns until the mapper saturates at 100%.
- Actual: recovery first frame is safely read-only, but the actual selected player saturates at **70%**. `_baseline_update` remains unconsumed at `0.2`. MPRIS translates `0.2 + incoming - 0.5`; the mapper's 1.0 ceiling therefore cannot reach actual 1.0.
- Cause: runtime baseline handshake is restricted to `native_output` (Windows/macOS), even though Linux MPRIS now exposes the same handshake. The immediate manual-switch path re-arms the Linux mapper and passes the separate positive test; delayed availability/recovery does not.
- Expected: recovery rebase must also synchronize the Linux mapper so subsequent endless turns can reach both actual endpoints without an unwind debt.
- Test: `test_linux_missing_manual_player_reappearance_keeps_full_range`.

## Additional specification/UX findings (not unconditional blockers)

### C1 — Manual selection silently overrides the enabled shake-to-change gesture

- Sources: Linux `mpris_volume.py:403–430, 446–454`; Windows `windows_audio.py:108–116, 223–227`; macOS `macos_audio.py:464–470, 555–560`.
- With A/B available, select A manually, then apply `cycle_player`. All three adapters accept it without error, but their next actual selection remains A: `_manual_player` wins over the cycle pin/selected value.
- The UI checkbox still says `Potrząśnięcie zmienia odtwarzacz`. The confirmed spec defines the two controls but does not explicitly resolve their interaction. If manual pinning intentionally disables gesture switching, make that policy clear in UI/docs (including that enabling the checkbox alone is insufficient). If the enabled gesture is intended to change the chosen player, this is a functional gap on all three platforms.
- Three parametrized red scratch assertions deliberately test the latter interpretation. Do not count them as unconditional requirement violations without resolving the policy.

### C2 — Direction-only native plane mappings retain an unsupported default trigger

- Source: `profiles/devices.py:307–311, 490–491`; Windows `output/windows_backend.py:145–153`; macOS `output/macos_backend.py:116–132`.
- Native plane opens with only `left -> key_a`, but pressing the still-default physical button generates logical `trigger`, which is not a native keyboard/mouse action. The independently exercised Windows receipt is `unsupported held input trigger`; macOS contains the equivalent rejection branch.
- Keyboard-only operation is explicitly supported and no virtual joystick should be invented. Users can avoid this by also setting `button=off` or a supported keyboard/mouse action. Clarify this required setup, or treat unsupported analog-only defaults as inactive in native binding-only mode. The current hint merely asks for one custom action and does not identify this remaining default-button limitation.
- Test: `test_plane_direction_only_native_mode_allows_default_physical_button` (an ergonomic expectation, not a demand for native HID support).

## Multimedia configurator blank screenshot: harness timing artifact confirmed

Parent screenshot `/home/jakub/.hermes/cache/scratch/triki-controls-screenshots/media-configurator.png` genuinely contains a blank page under the selected Multimedia tab. It was not an illusion or hidden below-fold content.

Independent reproduction `/home/jakub/.hermes/cache/scratch/triki_spec_ui_visibility.py` found:

| Sequence | Media page mapped | Player selector mapped |
| --- | --- | --- |
| Build plane form, immediately call `tabs.set('Multimedia')`, settle | 0 | 0 |
| Invoke already-selected Multimedia button afterward | 0 | 0 |
| Build form, settle, then call `tabs.set('Multimedia')` | 1 | 1 |
| Build form with media as initial session profile | 1 | 1 |

Cause: local CustomTkinter `CTkTabview.set` schedules a 100-ms `_grid_forget_all_tabs(exclude_name=name)` callback. `ConfigForm` selects its initial tab at `desktop.py:557–561`; the screenshot harness immediately selects another tab before the earlier timer drains. That earlier timer forgets the later tab, and the later timer does not re-grid it. Clicking an already-selected segmented button is a no-op. A different tab and back, or a subsequent delayed `.set`, restores it.

This does **not** establish that a normal user-selected Multimedia tab is blank. Capture after an initial event-loop settle or start the session on media; both are verified to render. An unusually fast tab switch during the first 100 ms can expose the toolkit race, but the supplied screenshot is not an unconditional product rendering blocker.

## Acceptance coverage and boundaries

- Additive settings vocabulary and schema1 old-file defaults: reviewed and executed; independent default/hysteresis probe passed.
- Sparse per-profile movement/button/click mappings and 20%/15% hysteresis: reviewed; new core/settings/routing tests independently passed. Original analog/default mapper paths are retained. Explicit held-button overrides suppress implicit click/recenter behavior; explicit click overrides may coexist.
- GUI draft propagation, profile-scoped collect, keyboard access, refresh keeping selected ID, minimum-size controls and Save flow: source reviewed and new real-Tk tests executed. Configurator content is scrollable; blank screenshot timing artifact investigated separately above.
- Selection enumeration: source listing paths do not intentionally select, rebase or write volume. Windows enumerations remain on the existing dedicated COM worker. Linux lazy catalog does not open UInput; owned MPRIS instance replacement on actual output open was reviewed. Session shutdown closes its separately constructed catalog.
- Native permissions/input ownership: Quartz checks Accessibility at open and posting, tracks held keys/buttons; native backend cleanup retains failed-release ownership. Existing/new inert-output tests pass. No claim of physical OS delivery or target-app consumption is made.
- Shake disable affects only `_update_shake`; inversion, system volume and media click/transport paths remain present. Manual-pin/gesture precedence remains C1.
- Stop/disconnect/reconfiguration release paths are integrated, not merely UI-only. Unsupported native steering/plane without custom input mappings still rejects accurately. Native custom steering/plane is keyboard/mouse-only, not virtual HID.
- User config files were not written by this review. No source fixes were made. Hardware Windows/macOS/BLE acceptance remains separate and unverified here.

**Publication recommendation:** do not promote this integration as specification-complete or publish the release until B1–B3 have fixes and green independent reproductions. Resolve/document C1 and C2 without disguising unavailable native HID/transport functionality. Re-capture the Multimedia configurator after the initial tab timer settles.
