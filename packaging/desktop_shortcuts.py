"""Install native shortcuts for a frozen executable; no app preference writes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

LAUNCHES = {
    "Triki Controller": ["gui"],
    "Triki Configurator": ["config"],
    "Triki AirMouse": ["mouse"],
    "Triki Wheel": ["wheel"],
    "Triki Music": ["music"],
    "Triki Plane": ["plane"],
    "Triki Tray": ["gui", "--tray"],
}


def bundled_icon(platform: str) -> str | None:
    """Official emblem inside the checkout or the frozen onedir bundle."""
    kind = {"linux": "png", "win32": "ico", "darwin": "icns"}.get(platform)
    if kind is None:
        return None
    try:
        from triki_controller.gui.app_icon import icon_file
    except ImportError:
        return None
    path = icon_file(kind)
    return str(path) if path is not None else None


def desktop_quote(value: str) -> str:
    # Desktop Entry Exec escaping differs from POSIX shell quoting.
    value = value.replace("%", "%%")
    for character in ("\\", '"', "`", "$"):
        value = value.replace(character, "\\" + character)
    return '"' + value + '"'


def install_shortcuts(executable: Path, destination: Path, platform: str | None = None) -> list[Path]:
    platform = platform or sys.platform
    if platform not in ("linux", "win32", "darwin"):
        raise ValueError(f"Unsupported shortcut platform: {platform}")
    executable = executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    destination.mkdir(parents=True, exist_ok=True)
    paths = []
    icon = bundled_icon(platform)
    for title, args in LAUNCHES.items():
        if platform == "linux":
            path = destination / (title.replace(" ", "-") + ".desktop")
            icon_line = f"Icon={icon}\n" if icon else ""
            path.write_text(
                "[Desktop Entry]\nType=Application\nVersion=1.0\n"
                f"Name={title}\nComment=Triki controller desktop\n"
                f"Exec={desktop_quote(str(executable))} {' '.join(args)}\n"
                f"{icon_line}"
                "Terminal=false\nCategories=Utility;\n", encoding="utf-8")
            path.chmod(0o755)
        elif platform == "darwin":
            path = destination / (title + ".command")
            path.write_text(f"#!/bin/sh\nexec {shlex.quote(str(executable))} "
                            + " ".join(map(shlex.quote, args)) + ' "$@"\n', encoding="utf-8")
            path.chmod(0o755)
        else:
            if sys.platform != "win32":
                raise RuntimeError("Real Windows .lnk creation requires native Windows PowerShell")
            path = destination / (title + ".lnk")
            quote = lambda s: "'" + str(s).replace("'", "''") + "'"
            icon_stmt = f"$s.IconLocation={quote(icon)};" if icon else ""
            script = (
                "$w=New-Object -ComObject WScript.Shell;"
                f"$s=$w.CreateShortcut({quote(path)});"
                f"$s.TargetPath={quote(executable)};"
                f"$s.Arguments={quote(subprocess.list2cmdline(args))};"
                f"$s.WorkingDirectory={quote(executable.parent)};{icon_stmt}$s.Save();"
                f"if (!(Test-Path -LiteralPath {quote(path)})) {{ exit 1 }}")
            subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], check=True)
        if not path.is_file():
            raise RuntimeError(f"Shortcut creation failed: {path}")
        paths.append(path)
    return paths


def activate_frozen_shortcuts() -> None:
    """Keep the existing GUI shortcut button working without modifying its source."""
    if not getattr(sys, "frozen", False):
        return
    from triki_controller.gui import shortcuts as existing

    def native_platform(value: str) -> str:
        return "win32" if value == "windows" else value

    def install(*, platform: str, python: str, pythonpath: str | None,
                directories: list[Path], create_windows_lnk: bool = True) -> list[Path]:
        result = []
        for directory in directories:
            result.extend(install_shortcuts(Path(sys.executable), directory, native_platform(platform)))
        return result

    def plan(*, platform: str, python: str, pythonpath: str | None,
             directories: list[Path]):
        native = native_platform(platform)
        extension = {"linux": ".desktop", "win32": ".lnk", "darwin": ".command"}[native]
        return [existing.PlannedShortcut(directory / ((title.replace(" ", "-") if native == "linux" else title) + extension), "")
                for directory in directories for title in LAUNCHES]

    # In-memory adapters only. Original Python/source entry points are unchanged.
    existing.install_shortcuts = install
    existing.plan_shortcuts = plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install shortcuts pointing directly to the frozen GUI")
    parser.add_argument("--dest", required=True, type=Path,
                        help="Explicit shortcut directory (no default/system directory writes)")
    args = parser.parse_args(argv)
    if not getattr(sys, "frozen", False):
        parser.error("Run install-shortcuts using the built TrikiController executable")
    paths = install_shortcuts(Path(sys.executable), args.dest)
    print(json.dumps([str(p) for p in paths], indent=2))
    return 0
