# Native output final offline verification — 2026-10-04

## Delivered integration

- Windows selects native Core Audio (separate application session and default system endpoint volume) and SendInput instead of Linux uinput.
- macOS selects its native audio/input adapters; player volume is limited to supported applications with their permissions.
- Linux output implementations and motion/profile/transport/protocol modules retain their baseline hashes.
- Target cycle, late availability and process-generation changes preserve the newly selected application's actual volume on the first frame. A native-only runtime handshake transfers the new baseline to the existing mapper before the following frame.
- Windows translation origin follows the mapper's new baseline. Native player endpoints 0% and 100% bypass sub-percent write suppression when needed, preserving complete knob travel.
- Failed apply does not consume the pending mapper baseline. Hook failures are reported in the existing receipt/lifecycle diagnostics rather than escaping dispatch.
- Native allocation/cleanup is transactional and stops dispatch before retryable release failures. Existing QA regressions cover visible errors and the independently identified failure cases.

## Executed verification

- Full project tests with local display and deterministic close-dialog response: **328 passed, 89 subtests passed, 3 hardware tests deselected**. No test failures or display skips. JUnit: `/home/jakub/.hermes/cache/scratch/triki-native-final-tests.xml`.
- Independent earlier QA defect reproductions: **7 passed**. JUnit: `/home/jakub/.hermes/cache/scratch/triki-native-spec-final.xml`.
- Excluded hardware-writing cases: `test_mouse_steering_and_media_roundtrip`, `test_uinput_media_routes_volume_to_mpris`, `test_uinput_transport_falls_back_when_mpris_rejects`.
- `git diff --check`: exit 0.
- Protected configurator methods `_show_configurator`, `_select_config_nav`, `_fill_config_body`, `_build_config_editor`, `_save_config`: AST-identical to saved original.
- User-settings SHA-256 matched its saved baseline. No settings writes in packaged GUI smoke.
- Linux build: `.venv/bin/python tools/build_desktop.py --target linux --smoke` exited 0.
- Complete Linux archive extracted to a separate scratch directory; relocated binary launched with `--smoke`, exited 0, opened/closed GUI, processed four fake samples, and reported `config_writes=0`.
- Artifact: `packaging/dist/TrikiController-linux-x86_64.tar.gz`.
- Archive SHA-256: `30bf4ca83a2ccb6d7e41025c0f26c49fb3eeb3020c91ef39ddd514520d5aef61`.
- Build receipt: `packaging/build/build-report.json`. Relocated receipt: `/home/jakub/.hermes/cache/scratch/triki-native-relocated-smoke.json`.

## Explicit limits / required native acceptance

These results validate offline adapters, real mapper/runtime behavior, GUI regression tests and a Linux frozen bundle. They do not validate physical Bluetooth/controller output, native Windows/macOS APIs or target OS frozen bundles.

Windows `.exe` and macOS `.app` must still be built and exercised on their respective hosts using `docs/native-desktop-build.md`. Use read-only `tools/accept_windows_output.py` or `tools/accept_macos_output.py` first; audio writes require explicit `--allow-write` and readback. Confirm per-app versus system volume, media routing, permissions, disappearance/reselection, shutdown/release, and actual device input.

Windows steering/plane modes are explicitly unsupported without a supported virtual HID driver. Windows global media keys are not guaranteed to target the pinned audio process. macOS application-volume support is application-dependent; Apple Events/Accessibility approval, signing and notarization are not certified here. Tray hiding only succeeds with an operational backend; otherwise the visible-window fallback avoids trapping the application.

A final optional Cursor read-only review exited 0 but returned no usable report; it is **not** counted as a completed independent review. The previous agent/provider failure was not treated as successful completion; its partial code was re-read, reproduced and repaired before all final tests/builds above.
