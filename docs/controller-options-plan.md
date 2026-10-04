# Controller options and media target selection

## User-confirmed scope

- Multimedia: toggle the shake gesture that changes players; manually choose the player actually controlled. Keep volume, mute, inversion and playback behavior unchanged otherwise.
- AirMouse, steering and plane: map physical button/click sequences and directional movement to chosen keyboard keys or mouse buttons, separately per profile.
- Test seams confirmed by user: additive GUI controls, compatible settings read/write, actual gesture/player behavior, mapping, Stop/disconnect release.

## Integration contracts

- GuiSettings optional fields: `media_gestures_enabled=True`, `media_player=None` (automatic), `control_bindings={}`. Existing schema1 settings load with defaults; user settings never overwritten automatically.
- Mapper APIs: `set_media_gestures_enabled(bool)`, `set_control_bindings(mapping)`; reset clears event state but retains options.
- Profile binding sources: `button`, `click`, `double_click`, `triple_click`, `left`, `right`, `forward`, `backward`.
- Actions: default/off, left/right/middle mouse buttons, alphabet/digit keys, arrows, space/enter/escape, shift/ctrl/alt/tab/backspace. Logical keyboard names `key_*` shared across backends.
- Directional activation/release uses normalized existing profile output with20% activation/15% release hysteresis; original analog output/default behavior preserved where supported.
- Held physical-button remapping takes precedence over legacy delayed click behavior to avoid duplicate actions.
- Backend APIs: `list_media_players()->list[tuple[id,label]]`; `select_media_player(id|None)`. Listing is observational; a missing explicitly selected player cannot silently fall back to another player/system master.
- Native player changes retain read-only first-frame baseline/rebase safeguards.
- Runtime passes media player/bindings to output open; native steering/plane can provide keyboard/mouse-only mode when explicitly configured. This is not virtual-HID/analog joystick support. No driver installation.

## Work partition

1. Core/settings: settings.py, mapper devices.py, new binding catalogue/validation and behavioral tests.
2. Native output/media: output modules, keyboard and mouse dispatch/cleanup, manual selection and inert-native tests.
3. GUI/runtime: additive UI, session/runtime settings integration and real-Tk tests.
4. Parent integration: original suite/independent regression runs, specification then code-quality review, UI exercise and documentation.
5. After implementation and verification, update README.md in Polish with practical instructions for all application sections: installation/launch on each platform, main menu/tray/shortcuts, BLE connection, configurator and save/reset, steering/AirMouse/plane controls, media volume/inversion/transport, gesture toggle/manual player picker, movement/button mapping, previews/diagnostics, Stop/disconnect cleanup, permissions and accurately stated platform limitations. Document actual final behavior and labels, not planned or unsupported features.

## Safety and acceptance

No configuration-file writes, real hardware output, commits, pushes or new releases during implementation. Existing settings file hash recorded in scratch. Physical Windows/macOS/Bluetooth acceptance remains separate. A UI-only selector or a passing mock without actual output-routing integration is not completion.
