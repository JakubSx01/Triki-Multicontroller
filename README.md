# Triki Controller (Linux MVP)

Offline **fake transport** plus a **provisional** Bleak BLE adapter and CAP001
`reference-hypothesis` parser derived from TrikiScope. Framing and the
2048 LSB/g, 131 LSB/(°/s) scales are **not** a HOM-27 sign-off.

`monitor` / `record` keep FILTERED → PROFILE MAPPING → FINAL OUTPUT unavailable.
`emulate` turns that path on for three profiles. Pitch and roll follow gravity.
Yaw is integrated only and drifts; it is not used as a heading.

Pipeline visibility: `RAW → FILTERED → PROFILE MAPPING → FINAL OUTPUT`.

## Application icon

The official icon is the neon low-poly controller emblem (Y mark). Source JPEG and the generated sizes live in `src/triki_controller/gui/assets/app_icon/`:

| File | Use |
| --- | --- |
| `source.jpg` | Original 1024×1024 emblem |
| `triki-controller.png` | 512×512 PNG for Linux `.desktop` `Icon=` and the Tk window |
| `triki-controller-<size>.png` | 16, 24, 32, 48, 64, 128, 256, 1024 |
| `triki-controller.ico` | Windows shortcut and PyInstaller `--icon` |
| `triki-controller.icns` | macOS app bundle (`PyInstaller --icon` when built on macOS) |

Regenerate after replacing `source.jpg`:

```bash
python3 tools/render_app_icon.py
```

The Tkinter window calls `iconphoto` (and `iconbitmap` on Windows). Linux shortcuts point `Icon=` at the PNG. The tray uses the same PNG. Frozen Windows and macOS builds embed `.ico` / `.icns`.

## Requirements

- Python 3.11+
- Offline fake mode: no third-party dependencies
- Desktop UI (default): Tkinter via CustomTkinter. `requirements.txt` lists it, or `pip install 'triki-controller[gui]'`. Linux also needs the system Tk package (`python3-tk`)
- Optional BLE: bleak in `requirements.txt` / `pip install 'triki-controller[ble]'`, plus BlueZ/D-Bus on Linux
- Live system input (mouse, wheel, media keys) is **Linux `/dev/uinput`** (`evdev`, `pywayland`). Windows and macOS run the panel, preview, and settings; they do not emit OS events

`requirements.txt` mirrors `pyproject.toml` extras (`gui`, `ble`, `uinput`). Core stays empty. Tray (`pystray`) and PyInstaller are not required to run from source; they are listed in `packaging/requirements-desktop.txt`.

## Install

From a checkout, with the desktop stack (GUI + BLE + Linux uinput):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip install -e .
```

Extras only, if you do not want the whole file:

```bash
python3 -m pip install -e '.[gui]'          # Tkinter desktop
python3 -m pip install -e '.[ble]'          # live BLE
python3 -m pip install -e '.[uinput]'       # Linux system input
python3 -m pip install -e '.[gui,ble,uinput]'
```

Without installing the package:

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main --help
```

## Commands

Monitor synthetic RAW stream:

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main monitor --transport fake --samples 8
```

Provisional live BLE monitor (host BlueZ required). Shows **Scanning for Triki**
and asks you to press the physical button **once** during the 30s scan:

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main monitor --transport ble --samples 50
```

Record CSV + `session.json` (same RAW path for fake or ble):

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main record --transport fake --samples 8 --out recordings/demo
```

Optional fake stress flags: `--reconnect-after N`, `--malformed`, `--split-frames`.

## Emulators

Live CAP001 → `/dev/uinput` (press the cap button once when asked to wake it):

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main emulate --profile steering --transport ble --live
PYTHONPATH=src python3 -m triki_controller.cli.main emulate --profile media --transport ble --live
```

| Profile | Gesture | Output |
| --- | --- | --- |
| `steering` | roll twist, vertical mount, full lock 90° | wheel; neutral at connect / button |
| `steering` | tip forward / back | throttle / brake on shared pitch; gas and brake each 8–40° |
| `steering` | physical button | recenter wheel/pedals to the current pose |
| `mouse` | air mouse: device X left/right, device Y front/back (horizontal, deadzone 10°) | pointer velocity |
| `mouse` | 1 click / 2 clicks | left / right mouse button |
| `media` | endless yaw knob (0–100%, no unwind past ends) | sets active-player volume via MPRIS (`playerctl`); soft-fails with status if Volume is not writable |
| `media` | 1 / 2 / 3 clicks | play/pause, next, previous — MPRIS first, then uinput media keys |
| `media` | flip onto the opposite face, then back | mute player (MPRIS Volume=0), then restore previous player volume |

**Muzyka** always uses **horizontal** mounting (no orientation choice). Home = pose at
connect/recenter; angle from that home maps to player volume like a real pot. Gravity
lean does not change volume. System-wide Pulse/`KEY_VOLUMEUP` is not used for volume.
Apps without writable MPRIS (e.g. Pear Desktop with Chromium MediaSession only) get a
clear Live status; enable Pear **Plugins → Shortcuts (& MPRIS)** for real player volume.

### Mounting orientation

Triki often sits flat (**Poziomo**). `--orientation` / `--rotation` remaps accel and gyro
**before** the tilt filter so pitch/roll match how you hold the cap (steering/mouse).
**Media ignores this flag** and stays horizontal. Invert flags remain separate sign flips.

| Id | Polish GUI label | Remap |
| --- | --- | --- |
| `horizontal` (default) | Poziomo | identity |
| `yaw_90` | Poziomo · obrót 90° | flat, +90° yaw |
| `yaw_180` | Poziomo · obrót 180° | flat, 180° yaw |
| `yaw_270` | Poziomo · obrót 270° | flat, +270° yaw |
| `vertical` | Pionowo | tip-up (pitch 90° remap) |
| `vertical_180` | Pionowo · obrót 180° | tip-up + 180° yaw |

Aliases: `poziomo`, `pionowo`, `90`, `180`, `270`. Axis signs stay
**reference-hypothesis**, not HOM-27 measured.

`--invert-pitch` and `--invert-roll` flip a sign if the cap is held the other way.
Disconnect, profile change, and exit release buttons and center absolute axes.
A grabbed uinput loopback checks the virtual device; that is not a game or a desktop volume check.

## GUI

The default interface is a **Tkinter** desktop window (CustomTkinter). There is
no browser UI in this package. It uses the same session, profiles, and
`~/.config/triki-controller/gui-settings.json`, and shows the official emblem
as the window icon.

```bash
PYTHONPATH=src .venv/bin/python -m triki_controller.cli.main gui
# after install:
triki-controller-gui
triki-controller gui --transport ble --connect
```

Quick profiles open a small status window, connect over BLE, and arm live output.
On Linux that output is uinput. On Windows and macOS the window still opens;
live OS events are not sent.

```bash
triki-controller mouse          # AirMouse
triki-controller wheel          # steering wheel
triki-controller music          # media keys / player volume
triki-controller mouse --dry-run
triki-controller mouse --no-window   # console status, no window
```

From a checkout, before `pip install`:

```bash
PYTHONPATH=src python3 -m triki_controller.cli.main mouse --dry-run --no-window
PYTHONPATH=src python3 -m triki_controller.cli.main wheel
PYTHONPATH=src python3 -m triki_controller.cli.main music
```

Console scripts after install: `triki-controller-mouse`, `triki-controller-wheel`,
`triki-controller-music`.

Axis configurator (live accel, gyro, tilt, mapped output preview, manual map).
It does **not** arm live uinput. Axis/threshold changes apply immediately in the
session; **Zapisz** writes `gui-settings.json`. Closing with unsaved edits asks
to confirm.

```bash
triki-controller config
triki-controller-config
```

Desktop launchers (Linux `.desktop` with the emblem `Icon=`, Windows `.bat`
plus `.lnk` with the `.ico` when PowerShell can create one, macOS `.command`;
the macOS `.app` icon is the `.icns` embedded at build time):

```bash
triki-controller shortcuts
triki-controller shortcuts --dry-run
PYTHONPATH=src python3 -m triki_controller.cli.main shortcuts
```

On Linux they land in `~/.local/share/applications` and on the desktop
(`XDG_DESKTOP_DIR`, otherwise `~/Desktop`). A desktop icon may need
“Allow Launching”. From a git checkout the launchers set `PYTHONPATH` to `src`
and point `Icon=` at `triki-controller.png` inside the tree.

`--connect` joins at startup. BLE: `--transport ble` (press the Triki button once
while scanning). The main panel does not arm output until you choose
**Próbne** or **Na żywo** (or pass `--live` / `--dry-run`). Quick commands arm
live output unless `--dry-run` is set.

Default map: yaw→wheel, pitch→throttle and pitch→brake (forward gas / back brake),
gyro Z/Y→mouse, yaw→volume. Existing `gui-settings.json` overlays are kept.
Accelerometer channels are shown (counts and m/s²) and are not themselves
control sources. Missing battery or RSSI stays unavailable.

| Control | Effect |
| --- | --- |
| Połącz / Rozłącz | BLE transport. |
| Kierownica / AirMouse / Multimedia | Profile switch (keeps BLE). |
| Wyzeruj | Recenter control origin (steering also recenters on the physical Triki button). |
| Stop | Stop output and neutralize axes. |

## Build

PyInstaller builds a native desktop folder on the OS you run it on. It is not
a cross-compiler: a Linux host produces the Linux bundle only. Windows `.exe`
and macOS `.app` (with `triki-controller.icns`) have to be built on those systems.
The Linux bundle does not embed an icon in the ELF; shortcuts use the PNG.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r packaging/requirements-desktop.txt
.venv/bin/python tools/build_desktop.py
```

Add `--smoke` on a machine with a working `DISPLAY` (Wayland needs XWayland).
That opens the GUI in dry-run and closes it. Without a display, skip `--smoke`
and check the CLI:

```bash
packaging/dist/TrikiController/TrikiController monitor --transport fake --samples 4
packaging/dist/TrikiController/TrikiController --help
```

| Platform | Artifact |
| --- | --- |
| Linux | `packaging/dist/TrikiController/TrikiController` plus `_internal/`. Archive: `packaging/dist/TrikiController-linux-<arch>.tar.gz` |
| Windows | `packaging/dist/TrikiController/TrikiController.exe` (icon from the `.ico`) |
| macOS | `packaging/dist/TrikiController.app` (icon from the `.icns`) |

Ship the whole directory, not the bootloader file alone. `pip install -e .` remains
the way to install into a normal Python environment. Frozen shortcuts:

```bash
packaging/dist/TrikiController/TrikiController install-shortcuts --dest "$HOME/.local/share/applications"
```

Create those after the bundle is in its final folder. Linux live mouse, wheel,
and media keys still need `/dev/uinput`. Windows and macOS builds run the GUI
only.

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

- Synthetic parser/stream tests remain labeled **synthetic**.
- CAP001 hypothesis tests use crafted 14-byte frames and are labeled **not measured**.
- Measured CAP001 protocol acceptance remains blocked on HOM-27.

## Layout

- `src/triki_controller/core` — immutable models
- `protocol` — synthetic-v0 + provisional `reference-hypothesis` CAP001 parser
- `transport` — fake async stream; optional `ble.py` (Bleak NUS)
- `recording` — RAW CSV v1 + session sidecar
- `output` — fake dry-run sink
- `motion` / `profiles` — mounting orientation remap + tilt filter + steering/mouse/media mappers
- `runtime` — pipeline boundaries + neutralize on disconnect; `emulate` path
- `gui` — Tkinter/CustomTkinter main menu (devices + shortcuts) + in-process configurator; official emblem in `gui/assets/app_icon/`; no web UI
- `output` — fake dry-run, trace, optional uinput; media volume via MPRIS/`playerctl`
- `cli` — `monitor` / `record` / `emulate` / `gui` / `config` / `mouse` / `wheel` / `music` / `shortcuts`
- `THIRD_PARTY_NOTICES.md` — MIT notice for TrikiScope-derived code
