# Windows native audio acceptance

## Scope and current verification boundary

Windows live output now selects `WindowsOutputBackend`, not Linux uinput.
Core Audio controls the selected application's audio sessions separately from
Windows' default multimedia output endpoint. Transport uses global media keys;
Windows decides which application handles them. Steering/plane virtual-gamepad
modes remain unsupported without a supported virtual HID driver. Linux output,
GUI elements and existing settings are unchanged by this native-output work.

Adapter tests on Linux are not evidence of audible output on Windows. Native
Windows and a physical Triki acceptance run remain required. The probe below
queries audio only; it does not exercise BLE, gestures, input injection or tray.

## Build on Windows

From the project directory in PowerShell, with native Python/Tk installed:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r packaging\requirements-desktop.txt
.venv\Scripts\python.exe tools\build_desktop.py --target win32 --console --smoke
# Final GUI build (no console):
.venv\Scripts\python.exe tools\build_desktop.py --target win32
```

Do not recreate an existing virtual environment blindly; use its interpreter if
it is already suitable. Distribute the complete generated folder/ZIP, not just
`TrikiController.exe`. The selected OS dependencies are platform-gated; these
commands do not change `pyproject.toml`, application settings or lockfiles.

## Read-only Core Audio probe

Start audio playback manually, then run:

```powershell
$env:PYTHONPATH = "src"
.venv\Scripts\python.exe tools\accept_windows_output.py
```

This queries current player sessions and the default system endpoint without
changing either volume. `--dry-run` validates arguments only and must not be
reported as native acceptance. A missing player session must remain an explicit
error, never a fallback to system volume.

Optional controlled writes, only when you intend to change actual volume:

```powershell
.venv\Scripts\python.exe tools\accept_windows_output.py --allow-write --player-index 0 --player-level 0.4
.venv\Scripts\python.exe tools\accept_windows_output.py --allow-write --system-level 0.4
```

Choose the player index from the read-only report. Writes verify native readback;
they do not restore the prior user volume. Changing the default endpoint during
the test invalidates the system write. Native readback is not a physical Triki
or human-listening certification.

## Physical controller acceptance

1. Open the packaged `music` shortcut. Confirm the app receives increasing samples
   and Live output is enabled: OS Bluetooth pairing alone is insufficient.
2. With the cap upright, turn it: selected application volume changes while system
   endpoint volume stays unchanged. Test an active browser/player audio session.
3. Invert the cap and turn it: system volume changes independently. Entry into
   inversion must not jump to an arbitrary level. Return upright; system level
   stays at the level the user set.
4. Check mute/unmute, cycle-player, play/pause, next and previous. Transport uses
   global Windows media-key routing and need not follow the pinned volume target.
5. Stop playback/close the selected app, change headphones/default endpoint,
   disconnect/reconnect Triki and recenter. Check error reporting and baseline
   capture; never treat a missing player as authorization to alter system volume.
6. Separately test mouse buttons/movement and verify button release on disconnect,
   deactivation and close. Virtual steering/joystick must show unsupported mode,
   not appear as a working controller.

Record Windows version, player name/version, source versus EXE, actual sample
rate, device/output mode, errors and results for each step. Do not include keys,
credentials or unrelated logs.
