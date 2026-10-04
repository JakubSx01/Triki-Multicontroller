# Controller options — final verification

## Implemented

- Media gesture toggle and manual player picker on device screens and configurator tabs. Manual pin blocks shake with a disabled toggle and visible explanation; returning to Auto restores the stored gesture policy.
- Per-profile button/one-two-three-click and directional mapping to keyboard/mouse actions for steering, AirMouse and plane. Existing unconfigured defaults are preserved; actions use20%/15% activation/release hysteresis. Windows/macOS steering/plane bindings are keyboard/mouse-only, not virtual analog HID.
- Explicit missing media targets fail closed. Player changes/reappearance synchronize actual-volume baselines without initial writes or range loss.
- Rejected live edits preserve accepted settings. Managed output disables dispatch before cleanup, retains failed-release ownership, exposes Off/error and supports retry without automatic Live reactivation, including uinput.
- Polish README covers all application screens, controls, installation, platform differences, mappings, saving, calibration, tray/shortcuts, CLI and troubleshooting.24 CLI examples were parsed by the documentation specialist. Source `emulate` currently does not load the new optional GUI controls; README states this boundary.

## Executed receipts

- Parent full display suite: **494 passed,89 subtests passed,3hardware tests deselected**. Real `evdev.UInput` globally denied; dirty-close dialogs answered deterministically. Receipt `/home/jakub/.hermes/cache/scratch/triki-controls-final.xml`.
- Independent specification +quality probes after fixes: **12 passed,3policy-dependent assertions excluded**. The excluded interpretation allowed shake to override a manual pin; the explicitly documented chosen policy is the opposite.
- Earlier native regression probes: **7 passed**.
- Linux build with `--smoke`: exit0. Complete archive extracted outside the project and relocated binary smoke: exit0, GUI opened/closed,4fake samples,`config_writes=0`. Receipt `/home/jakub/.hermes/cache/scratch/triki-controls-relocated-smoke.json`.
- Real-Tk screenshots checked at620×700 and configurator1100×720. Initial blank tab was reproduced as a toolkit/harness timing issue; starting on media renders legacy/new controls.
- Original configurator widget builders remain hash-protected. Tests normalize only explicit approved additions; no existing slider/map builders removed or redesigned.
- `git diff --check` passed. Actual saved user configuration matched its initial SHA-256 before publication.

## Safety boundaries

All final test receipts are offline/inert, not physical-controller or real Windows/macOS target-app certification. An earlier implementer accidentally ran two existing emitting-uinput cases; all subsequent QA added a hard denial of real UInput and explicit hardware-test exclusions.

Spec/quality findings and initial red reproductions remain documented in `controller-options-spec-review.md` and `controller-options-quality-review.md`, with resolution updates. No Jev provider call was made because credentials were absent; independent agent review and deterministic tests were used, without presenting them as Jev.

Native GitHub Actions build receipts and published v0.1.2 asset hashes are verified separately by the parent after committing this source snapshot. Existing runtime configuration files and GitHub workflow are not modified by this work.
