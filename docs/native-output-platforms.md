# Native output platforms

## Routing

Live output uses `output.platform_backend.create_live_output()`:

| Host `sys.platform` | Adapter | Live modes |
| --- | --- | --- |
| `linux*` | Existing `UInputBackend` | media, mouse, steering, plane (existing Linux implementation) |
| `win32` | `WindowsOutputBackend` | media, mouse |
| `darwin` | `MacOSOutputBackend` | media, mouse |
| Other | Explicit unsupported-platform error | None; use dry-run |

Only the selected adapter is imported. There is no Linux fallback on Windows or
macOS. GUI sessions, direct `emulate --live`, and quick launchers share this
routing. A source launch and a frozen executable make the same platform choice;
freezing must include the selected modules and their native dependencies.

`emulate` without `--live`, or quick commands with `--dry-run`, keep `TraceOutput`.
They record mapped controls without sending native input. Unsupported live modes
can still be previewed in dry-run. Configurator behavior and saved settings are
unchanged; choosing a quick profile changes the session in memory only.

The runtime's legacy `claim_uinput` capability remains the live-output flag for
compatibility. It does **not** mean that Windows or macOS use Linux uinput, or
that either native backend creates a discoverable virtual controller.

## Capability limits

- **Linux:** unchanged evdev/uinput implementation and permissions. Media player
  control remains MPRIS/playerctl; system-volume handling stays in the existing
  Linux mixer adapter. Device creation requires access to `/dev/uinput`.
- **Windows:** native mouse/media-key injection and Core Audio session/endpoint
  volume. Media keys are global Windows events: their application routing is not
  guaranteed to follow the selected audio session. Player/session volume is
  separate from system endpoint volume; lack of a usable session must not be
  disguised as success or silently converted into a system-volume change.
- **macOS:** native pointer events and media control for supported running
  Music/Spotify applications. Player control depends on scripting terminology,
  installed application support, and Automation permission. Browser/per-tab
  player volume is not supported. System output devices with fixed volume may
  reject volume changes. Pointer control requires Accessibility permission.
- **Windows/macOS steering and plane:** rejected with a driver/unsupported-mode
  error. No virtual HID/gamepad driver is included. Posting pointer events is
  not joystick support, and a mapped wheel axis is not a virtual steering wheel.

Native errors are reported rather than redirected through Linux tools. GUI
activation failures leave output Off; CLI activation failures return status 2.
Normal deactivation/disconnect uses the existing neutralize/close lifecycle.
This cannot guarantee cleanup after forced termination or a system crash.

## Dependencies and permissions

Install dependencies on their target OS, not into Linux just to satisfy imports:

- Windows audio: `pycaw`, `comtypes`, and `psutil` for Core Audio/session handling.
  Native `SendInput` itself is provided by Windows. Input/volume control remains
  subject to OS privileges and application/session availability.
- macOS: PyObjC framework packages used by the adapters:
  `pyobjc-framework-Cocoa`, `pyobjc-framework-ScriptingBridge`, and
  `pyobjc-framework-Quartz`. Grant Automation permission for player control and
  Accessibility permission for mouse events. System volume uses `osascript`.
- Linux: retain existing `evdev`, `playerctl`, and mixer/tool requirements.

Packaging requirements are managed separately from this routing layer.

## Verification boundary

`tests/test_platform_output.py` exercises lazy dispatch, unchanged Linux adapter
selection, GUI defaults and activation notes, quick autostart, source/frozen
routing, unknown-platform handling, and real native-mode rejection before OS
APIs. Native modules can be mocked at the dispatcher boundary without pretending
that native APIs were exercised. Existing Linux tests remain the regression
baseline.

Linux-hosted tests do not establish that Windows/macOS permissions, Core Audio,
Quartz, AppleEvents, or a real player accept the emitted controls. Verify media
transport, selected-player volume, system-volume restore, mouse-button release,
and disconnect cleanup on each target OS before claiming hardware/native
integration success. Frozen binary smoke tests are also separate from a
`sys.frozen` routing mock.
