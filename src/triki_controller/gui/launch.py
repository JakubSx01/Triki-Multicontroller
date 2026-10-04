"""Quick-launch wiring and headless status loop. No Tk and no display."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from triki_controller.core.models import ConnectionState
from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import SettingsError, default_settings_path, load_settings

QUICK_PROFILES = {
    "mouse": "mouse",
    "wheel": "steering",
    "music": "media",
    "plane": "plane",
}

GUI_MISSING_MESSAGE = (
    "Brak CustomTkinter. Zainstaluj: pip install 'triki-controller[gui]' "
    "(albo: pip install customtkinter). "
    "Linux: potrzebny też systemowy Tk (pakiet python3-tk)."
)

# Back-compat alias for older callers/tests.
TK_MISSING_MESSAGE = GUI_MISSING_MESSAGE


def virtual_input_note() -> str | None:
    """Live mouse, wheel, and keys use the Linux uinput backend."""
    if sys.platform.startswith("linux"):
        return None
    return (
        "Wyjście na żywo używa Linux uinput. "
        "Na tym systemie działa panel, podgląd osi i zapis ustawień."
    )


def apply_quick_profile(session: ControllerSession, command: str) -> str | None:
    """Switch profile in memory. Does not write gui-settings.json."""
    try:
        profile = QUICK_PROFILES[command]
    except KeyError:
        return f"Nieznany tryb {command!r}"
    return session.set_profile(profile)


class OutputAutostart:
    """Arm output once when a connection starts streaming."""

    def __init__(self, session: ControllerSession, *, live: bool, enabled: bool = True) -> None:
        self.session = session
        self.live = live
        self.enabled = enabled
        self._armed = False
        self.last_error: str | None = None

    def tick(self) -> str | None:
        if not self.enabled:
            return None
        snap = self.session.snapshot()
        streaming = snap.connection == ConnectionState.STREAMING
        if streaming and not self._armed:
            self._armed = True
            if snap.output_mode == OutputMode.OFF:
                self.last_error = self.session.start_output(live=self.live)
                return self.last_error
            return None
        if not streaming:
            self._armed = False
        return None


def open_session(args: argparse.Namespace) -> tuple[ControllerSession, Path, str | None]:
    """Load settings the same way as the desktop GUI. Parse errors are skipped."""
    path: Path = args.settings or default_settings_path()
    note: str | None = None
    try:
        settings = load_settings(path)
    except (OSError, SettingsError) as exc:
        note = f"Pominięto plik ustawień {path}: {exc}"
        settings = None
    session = ControllerSession(
        settings=settings,
        ble_scan_timeout_s=float(getattr(args, "scan_timeout", 30.0)),
    )
    return session, path, note


def run_headless(args: argparse.Namespace) -> int:
    """Console status loop for mouse / wheel / music when no window is wanted."""
    session, path, note = open_session(args)
    if note:
        print(note, file=sys.stderr)
    if args.command in QUICK_PROFILES:
        err = apply_quick_profile(session, args.command)
        if err:
            print(err, file=sys.stderr)
            session.shutdown()
            return 2
    live = not bool(getattr(args, "dry_run", False))
    profile = session.snapshot().profile_name
    print(
        f"QUICK profile={profile} transport={args.transport} live={str(live).lower()} settings={path}",
        flush=True,
    )
    err = session.connect(args.transport)
    if err:
        print(err, file=sys.stderr)
        session.shutdown()
        return 2
    auto = OutputAutostart(session, live=live)
    deadline = None
    auto_close = getattr(args, "auto_close", None)
    if auto_close:
        deadline = time.monotonic() + float(auto_close)
    last_print = 0.0
    last_summary = ""
    try:
        while deadline is None or time.monotonic() < deadline:
            start_err = auto.tick()
            if start_err:
                print(start_err, file=sys.stderr)
            snap = session.snapshot()
            rate = "—" if snap.sample_rate_hz is None else f"{snap.sample_rate_hz:.0f}"
            summary = f"state={snap.connection.value} output={snap.output_mode.value}"
            now = time.monotonic()
            if summary != last_summary or now - last_print >= 1.0:
                print(
                    f"{summary} samples={snap.samples} rate={rate}Hz",
                    flush=True,
                )
                last_summary = summary
                last_print = now
            if snap.connection == ConnectionState.ERROR:
                if snap.connection_reason:
                    print(snap.connection_reason, file=sys.stderr)
                return 2
            time.sleep(0.05)
        return 0
    except KeyboardInterrupt:
        print("\nZamykanie…", flush=True)
        return 0
    finally:
        session.shutdown()


def _forward(command: str, argv: list[str] | None) -> int:
    from triki_controller.cli.main import main as cli_main

    extra = list(sys.argv[1:] if argv is None else argv)
    return cli_main([command, *extra])


def gui_main(argv: list[str] | None = None) -> int:
    return _forward("gui", argv)


def config_main(argv: list[str] | None = None) -> int:
    return _forward("config", argv)


def mouse_main(argv: list[str] | None = None) -> int:
    return _forward("mouse", argv)


def wheel_main(argv: list[str] | None = None) -> int:
    return _forward("wheel", argv)


def music_main(argv: list[str] | None = None) -> int:
    return _forward("music", argv)
