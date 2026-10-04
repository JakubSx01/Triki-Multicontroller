"""Frozen desktop entry: the GUI is default; existing CLI commands stay available."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


def smoke() -> int:
    """Exercise actual fake parser/runtime and actual Tk, never user settings/BLE/input."""
    from triki_controller.cli.main import main as cli_main
    from triki_controller.gui.launch import gui_main

    keys = ("HOME", "XDG_CONFIG_HOME", "APPDATA", "LOCALAPPDATA")
    previous = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(prefix="triki-desktop-smoke-") as directory:
        try:
            for key in keys:
                os.environ[key] = directory
            # This produces real synthetic RAW samples; not fabricated output.
            result = cli_main(["monitor", "--transport", "fake", "--samples", "4"])
            if result:
                return result
            result = gui_main(["--dry-run", "--auto-close", "0.8", "--settings",
                               str(Path(directory) / "never-written.json")])
            # CustomTkinter installs bundled fonts under HOME/.fonts on Linux.
            # Those are disposable font-cache files, not application preferences.
            def font_cache(path: Path) -> bool:
                parts = path.relative_to(directory).parts
                return parts[0] == ".fonts" or parts == (".cache",) or parts[:2] == (".cache", "fontconfig")
            unexpected = [p.relative_to(directory) for p in Path(directory).rglob("*")
                          if not font_cache(p)]
            if unexpected:
                raise RuntimeError(f"Smoke unexpectedly wrote app settings: {unexpected}")
            if result == 0:
                print("DESKTOP_SMOKE_OK fake_samples=4 gui=opened-and-closed config_writes=0", flush=True)
            return result
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def run_tray(argv: list[str]) -> int:
    """Optional tray around the existing desktop; never replaces configurator logic."""
    import argparse
    import tkinter as tk
    from triki_controller.cli.main import add_gui_args, build_parser
    from triki_controller.gui.desktop import TrikiDesktop
    from triki_controller.gui.launch import QUICK_PROFILES, apply_quick_profile, open_session
    from triki_controller.gui.tray import QuickLaunchTray

    argv = [value for value in argv if value != "--tray"]
    if not argv or argv[0].startswith("--"):
        argv.insert(0, "gui")
    parser = build_parser()
    if argv[0] == "plane":
        parser = argparse.ArgumentParser(prog="TrikiController plane")
        add_gui_args(parser)
        parser.add_argument("--live", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        args = parser.parse_args(argv[1:])
        args.command = "plane"
    else:
        args = parser.parse_args(argv)
    if args.command not in ("gui", "config", *QUICK_PROFILES):
        parser.error("--tray requires a GUI or quick-profile command")
    if getattr(args, "no_window", False):
        parser.error("--tray and --no-window cannot be combined")
    if getattr(args, "live", False) and getattr(args, "dry_run", False):
        parser.error("--live and --dry-run cannot be combined")
    session, path, note = open_session(args)
    if note:
        print(note, file=sys.stderr)
    if args.command in QUICK_PROFILES:
        error = apply_quick_profile(session, args.command)
        if error:
            session.shutdown()
            print(error, file=sys.stderr)
            return 2
    try:
        app = TrikiDesktop(session, path,
            view="config" if args.command == "config" else "quick" if args.command in QUICK_PROFILES else "panel",
            transport=args.transport, connect=args.connect,
            live=bool(getattr(args, "live", False)), dry_run=bool(getattr(args, "dry_run", False)),
            auto_close=args.auto_close,
            quick_command=args.command if args.command in QUICK_PROFILES else None)
    except tk.TclError as exc:
        session.shutdown()
        print(f"Cannot open desktop display: {exc}", file=sys.stderr)
        return 1
    tray = app._tray or QuickLaunchTray(
        app.root, on_quit=app.close,
        on_error=lambda message: print(message, file=sys.stderr),
    )
    # Close hides only after the backend confirms an operational visible icon.
    # Quit retains the app's existing discard-confirmation and shutdown behavior.
    app.root.protocol("WM_DELETE_WINDOW", lambda: tray.hide() or app.close())
    app.root.bind("<Destroy>", lambda event: tray.stop() if event.widget is app.root else None, add="+")
    tray.start()
    try:
        app.run()
    finally:
        tray.stop()
        session.shutdown()
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if getattr(sys, "frozen", False):
        from desktop_shortcuts import activate_frozen_shortcuts
        activate_frozen_shortcuts()
    if "--tray" in argv:
        return run_tray(argv)
    if argv == ["--smoke"]:
        return smoke()
    if argv and argv[0] == "install-shortcuts":
        from desktop_shortcuts import main as shortcuts_main
        return shortcuts_main(argv[1:])
    from triki_controller.gui.launch import gui_main
    if not argv or argv[0].startswith("--") and argv[0] not in ("--help", "--version"):
        return gui_main(argv)
    from triki_controller.cli.main import main as cli_main
    # Older checkouts omitted the plane quick alias, although the desktop/session
    # already support it. Only the packaging entry adds that missing route.
    if argv[0] == "plane":
        from triki_controller.cli.main import build_parser, add_gui_args
        parser = build_parser()
        sub = next(a for a in parser._actions if hasattr(a, "choices") and isinstance(a.choices, dict))
        if "plane" not in sub.choices:
            import argparse
            p = argparse.ArgumentParser(prog="TrikiController plane")
            add_gui_args(p)
            p.add_argument("--live", action="store_true")
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--no-window", action="store_true")
            args = p.parse_args(argv[1:])
            args.command = "plane"
            if args.no_window:
                from triki_controller.gui.launch import run_headless
                return run_headless(args)
            from triki_controller.gui.desktop import run_desktop
            return run_desktop(args)
    return cli_main(argv)


if __name__ == "__main__":
    # Windowed builds have no standard streams, but the app still prints status.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    raise SystemExit(main())
