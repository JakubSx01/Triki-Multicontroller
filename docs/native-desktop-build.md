# Native desktop packaging

Build on the destination operating system with its native Python and dependencies
from `packaging/requirements-desktop.txt`. The helper rejects cross-compilation.
It does not change the GUI, configurator, or user settings. Dependency installation
and release signing are separate operations, not performed by the helper.

## Commands

From the repository root, using that OS's existing build environment:

```sh
# Linux
.venv/bin/python tools/build_desktop.py --target linux --smoke
# macOS: windowed .app, including privacy metadata
.venv/bin/python tools/build_desktop.py --target darwin --smoke
# macOS diagnostic executable (not an .app)
.venv/bin/python tools/build_desktop.py --target darwin --console --smoke
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe tools/build_desktop.py --target win32 --smoke
```

`--smoke` requires a desktop display and exercises fake controller samples and a
dry-run GUI; it does not certify Bluetooth, live native input/audio, tray behavior,
or operating-system permissions. `--command-only` prints the requested native
PyInstaller argument list without dependency preflight, building, or file writes.
For a macOS .app this is the input recipe, not the final spec-build command.

## Platform dependency boundary

Preflight and collection use the same platform-specific module lists:

| Target | Required and explicitly collected native modules |
| --- | --- |
| Linux | `evdev`, `pywayland` |
| Windows | `pycaw`, `comtypes`, `psutil` |
| macOS | `AppKit`, `Foundation`, `ScriptingBridge`, `Quartz`, `objc` |

The macOS modules come from PyObjC Cocoa, ScriptingBridge, Quartz, and core;
Windows dependencies remain Windows-only and PyObjC remains macOS-only in the
requirements file. Missing native modules fail preflight before PyInstaller runs.
The package's existing platform factory is collected along with application
submodules; source and frozen launches retain the same host selection instead of
introducing a packaging-only fallback to Linux.

## macOS privacy metadata and signing order

The default windowed macOS build generates these **build artifacts only**:

- `packaging/build/TrikiController.spec`
- `packaging/build/macos-entitlements.plist`

The helper first writes an entitlement plist containing
`com.apple.security.automation.apple-events = true`. It generates a spec using
`PyInstaller.utils.cliutils.makespec`, preserving the recipe's collection,
icon, bundle identifier, and entitlement options while removing execution-only
`--noconfirm`, `--clean`, `--distpath`, and `--workpath` arguments.

Before running PyInstaller on that spec, an AST transformation inserts
`NSAppleEventsUsageDescription` into `BUNDLE(info_plist=...)`. Existing literal
metadata, including a nonempty custom usage description, is preserved. A missing
`info_plist` keyword or `None` is initialized; a missing/ambiguous `BUNDLE`, dynamic
metadata, invalid privacy text, or unsupported plist values fails loudly. A stale
spec is removed before generation, so a failed generator cannot reuse it.

PyInstaller then receives the generated spec plus execution-only output options.
The final `.app/Contents/Info.plist` is read back and checked; **it is never edited
after bundle construction/signing**. The console diagnostic path produces no
`.app`, and intentionally does not claim the .app's usage-description or
entitlement configuration. Test source and diagnostic permissions separately
from the actual distributed .app.

### Distribution limitations

The helper supplies no Developer ID signing identity: PyInstaller's documented
macOS default is ad-hoc signing. Ad-hoc is **not unsigned**, but also is **not** a
trusted Developer ID release or notarization. PyInstaller can warn and continue
when final bundle signing fails; inspect `pyinstaller.log` and verify the final
signature on macOS before claiming that even ad-hoc signing succeeded. No certificate/keychain changes,
notarization submission, stapling, Gatekeeper bypass, or permission grants are
performed. The Apple Events entitlement and purpose string do not grant user
Automation consent; live player control still requires host permission and native
validation. Accessibility/input permissions are also a separate host concern.

A release maintainer must use an appropriate Developer ID identity and hardened
runtime configuration, review the entitlements needed by the complete app,
validate signatures and native behavior, and complete Apple's notarization and
stapling workflow. Add/review privacy metadata **before** signing; changing the
final plist is not a safe way to repair a signed bundle. Do not describe the
helper's local archive as an unsigned, trusted, notarized, or platform-certified
release without independent evidence.

## Reports and verification

`packaging/build/build-report.json` keeps the executable and whole-archive paths
and SHA-256 hashes, platform/machine/Python, assets, and `smoke_exit_code`.
Additional fields distinguish the recipe from the command actually executed:

- `requested_command`: original native collection recipe.
- `command`: actual build command; for a macOS .app, this consumes the spec.
- `spec_generation_command`: actual makespec command, or `null` elsewhere.
- `bundle_info_plist`: metadata injected and checked, or `null` for non-.app builds.
- `entitlements_file`: generated build-artifact path, or `null` elsewhere.
- `signing_mode`: `pyinstaller-default-ad-hoc` on macOS, otherwise `null`;
  this identifies the requested default, not an independent signature audit.
- `notarized`: always `false`; this helper does not notarize.

Tests use platform patches, generated-spec fixtures, and mocked build output:

```sh
.venv/bin/python -m pytest tests/test_desktop_packaging.py tests/test_native_desktop_packaging.py -q
```

Passing these checks on Linux is not Windows/macOS certification. Real native
builds, signature inspection, privacy dialogs, and input/audio checks must run on
the respective OS. The tests do not execute a cross-compiled application.

## Authoritative references

- PyInstaller CLI/spec options: <https://www.pyinstaller.org/en/stable/usage.html>
- PyInstaller bundle metadata: <https://pyinstaller.org/en/stable/spec-files.html>
- Apple Events purpose string: <https://developer.apple.com/documentation/bundleresources/information-property-list/nsappleeventsusagedescription>
- Apple Events entitlement: <https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.automation.apple-events>
- Apple notarization: <https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution>
