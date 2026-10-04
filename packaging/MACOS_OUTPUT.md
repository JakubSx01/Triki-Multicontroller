# macOS native output (native acceptance pending)

Added backend: `triki_controller.output.macos_backend.MacOSOutputBackend`.
No GUI/configuration/BLE/profile/Linux-output changes are made by this implementation.

## Contracts and limits

- `media`: `player_volume` is the existing absolute [0,1] app level. `system_volume`
  is an offset present only while the profile is inverted, **not** a system level.
  First system offset captures the actual level and mapped origin without a write.
  Leaving inversion/neutralizing/closing never restores any previous user volume.
- Running Music and Spotify only; selection is deterministic, `cycle_player` pins
  the next supported running app. Mute saves/restores volume per app and is not
  overwritten by the same frame's player-volume axis. Transport: `playpause`,
  `next track`, `previous track`; volume: `sound volume` (0–100). Each installed
  app's real `sdef` dictionary must expose the requested term before use.
- ScriptingBridge uses an existing process ID, not a bundle initializer, never
  `activate`, `launch`, or `open`. A missing/stopped app is an error; no app launch
  or fallback to system volume. Browser/Pear/arbitrary-app audio is unsupported.
- System volume uses Standard Additions `get volume settings` / `set volume
  output volume`; write readback detects fixed-volume output devices.
- `mouse`: Quartz pointer deltas, fractional accumulation, left/right clicks,
  drag events, held releases. Permissions checked before posting. Posting has no
  target-app delivery acknowledgment. Arbitrary keyboard keys/global media keys
  are deliberately unsupported rather than guessing special-event encodings.
- `plane`/`steering`: explicit unsupported virtual joystick/HID-driver error.
- Receipts preserve RAW lineage and activation epochs. Stale samples emit nothing.
  Output/permissions errors produce `applied=False`, `stage_status=ERROR`. Some
  outputs may already have occurred before an error; receipts are not atomic.
- `dry_run` never invokes audio/input adapters or emits native events. A legacy
  `claim_uinput` capability is accepted as live authorization only, for session
  compatibility; no evdev/uinput is used. `claim_native` is also accepted.

## Packaging requirements (not yet added to existing packaging files)

Install on macOS only, with wheels matching the selected Python/macOS version:

```sh
python -m pip install pyobjc-framework-Cocoa pyobjc-framework-ScriptingBridge pyobjc-framework-Quartz
```

`osascript` and `sdef` are OS tools. Cocoa + ScriptingBridge enable player control;
Quartz enables pointer output. Lazy imports keep Linux tests independent of these.
Quartz event-post preflight requires macOS 10.15+ (and the chosen PyObjC version
may require a newer OS). Check Python 3.14 wheel availability in the macOS build.
Freezers should explicitly collect the `AppKit`, `Foundation`, `ScriptingBridge`,
`Quartz`, and `objc` modules/framework support (lazy imports).

For the packaged app, provide `NSAppleEventsUsageDescription` in Info.plist and
sign with appropriate automation/hardened-runtime entitlement
`com.apple.security.automation.apple-events` when applicable. Users must grant
Privacy & Security > Automation for Music/Spotify and Accessibility for mouse
output to the actual hosting app/terminal. This implementation does not request
permissions automatically, and is not a claim of App Sandbox support. Permission
failures/AppleEvent error -1743 are reported instead of success.

## Acceptance

```sh
PYTHONPATH=src python -m unittest discover -s tests -p test_macos_output.py
PYTHONPATH=src python tools/accept_macos_output.py --dry-run
# On a Mac, read-only audio queries and permission preflight (may prompt Automation):
PYTHONPATH=src python tools/accept_macos_output.py
# Only with explicit user approval, changes actual volume, without restoring it:
PYTHONPATH=src python tools/accept_macos_output.py --allow-write --player Music --player-level 0.4
```

Default probe never writes volume, posts input, sends transport, or launches apps.
Only apps already running are queried. Run with both apps closed to verify no
launch; then open each manually and verify dictionary/readback/permissions. An
AppleEvent reply alone is not proof of audible playback; transport and pointer
consumption require a human on the target Mac. Test device changes, denial and
revocation of permissions, cycles/mute per app, inversion/reentry, disconnect and
release, and packaged-app signing separately. Linux adapter tests are not native
acceptance. No macOS host was available for this implementation.

## Official API references consulted

- Apple Standard Additions commands: https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleScriptLangGuide/reference/ASLR_cmds.html
- ScriptingBridge: https://developer.apple.com/documentation/scriptingbridge/sbapplication
- PID initializer: https://developer.apple.com/documentation/scriptingbridge/sbapplication/init(processidentifier:)
- Last error: https://developer.apple.com/documentation/scriptingbridge/sbobject/lasterror()
- AppleEvent timeout ticks: https://developer.apple.com/library/archive/documentation/AppleScript/Conceptual/AppleEvents/create_send_aepg/create_send_aepg.html
- Quartz event services: https://developer.apple.com/documentation/coregraphics/quartz_event_services
