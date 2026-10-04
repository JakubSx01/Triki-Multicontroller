"""Desktop launchers for the panel, AirMouse, steering wheel, and media.

Linux: .desktop in the app menu and on the desktop (or Pulpit from user-dirs).
Windows: .bat starters; a .lnk is added when PowerShell is available.
macOS: executable .command files on the Desktop and in ~/Applications.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHORTCUT_SPECS: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    (
        "triki-controller",
        "Triki Controller",
        "Panel sterowania Triki",
        ("gui",),
    ),
    (
        "triki-mouse",
        "Triki AirMouse",
        "Szybki start myszy (BLE, wyjście na żywo)",
        ("mouse", "--transport", "ble"),
    ),
    (
        "triki-wheel",
        "Triki Kierownica",
        "Szybki start kierownicy (BLE, wyjście na żywo)",
        ("wheel", "--transport", "ble"),
    ),
    (
        "triki-music",
        "Triki Multimedia",
        "Szybki start sterowania muzyką (BLE, wyjście na żywo)",
        ("music", "--transport", "ble"),
    ),
)


def application_icon(kind: str = "png") -> str:
    """Absolute path to the official emblem, or a theme name if the file is missing."""
    from triki_controller.gui.app_icon import icon_file

    path = icon_file(kind)
    return str(path) if path is not None else "triki-controller"


@dataclass(frozen=True)
class PlannedShortcut:
    path: Path
    content: str
    executable: bool = False


def normalize_platform(name: str | None = None) -> str:
    raw = (name or sys.platform).lower()
    if raw.startswith("linux"):
        return "linux"
    if raw.startswith("win"):
        return "windows"
    if raw == "darwin" or raw.startswith("mac"):
        return "darwin"
    return raw


def bundled_source_path() -> str | None:
    """PYTHONPATH=src when this file lives in a checkout, not in site-packages."""
    here = Path(__file__).resolve()
    src = here.parents[2]
    root = src.parent
    if (root / "pyproject.toml").is_file() and (src / "triki_controller" / "__init__.py").is_file():
        return str(src)
    return None


def desktop_directory(home: Path) -> Path:
    config = home / ".config" / "user-dirs.dirs"
    if config.is_file():
        text = config.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("XDG_DESKTOP_DIR"):
                continue
            _, _, raw = stripped.partition("=")
            raw = raw.strip().strip('"').strip("'")
            raw = raw.replace("${HOME}", str(home)).replace("$HOME", str(home))
            return Path(raw).expanduser()
    return home / "Desktop"


def default_directories(home: Path, platform: str) -> list[Path]:
    desktop = desktop_directory(home)
    if platform == "linux":
        return [home / ".local" / "share" / "applications", desktop]
    if platform == "windows":
        menu = home / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        return [desktop, menu]
    if platform == "darwin":
        return [desktop, home / "Applications"]
    return [desktop]


def command_argv(python: str, args: tuple[str, ...]) -> list[str]:
    return [python, "-m", "triki_controller.cli.main", *args]


def _desktop_quote(arg: str) -> str:
    if arg == "" or any(ch in arg for ch in ' \t\n"\'\\$`'):
        escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return arg


def linux_desktop_entry(
    *,
    title: str,
    comment: str,
    argv: list[str],
    icon: str,
    pythonpath: str | None,
) -> str:
    exec_args = list(argv)
    if pythonpath:
        exec_args = ["env", f"PYTHONPATH={pythonpath}", *exec_args]
    exec_line = " ".join(_desktop_quote(part) for part in exec_args)
    return (
        "[Desktop Entry]\n"
        "Version=1.0\n"
        "Type=Application\n"
        f"Name={title}\n"
        f"Comment={comment}\n"
        f"Exec={exec_line}\n"
        "Terminal=false\n"
        "Categories=Utility;\n"
        f"Icon={icon}\n"
        "StartupNotify=true\n"
    )


def windows_bat(argv: list[str], pythonpath: str | None) -> str:
    lines = ["@echo off", "setlocal"]
    if pythonpath:
        lines.append(f'set "PYTHONPATH={pythonpath}"')
    program, *rest = argv
    lines.append(subprocess.list2cmdline([program, *rest]))
    lines.append("")
    return "\r\n".join(lines)


def macos_command(argv: list[str], pythonpath: str | None) -> str:
    import shlex

    lines = ["#!/bin/bash"]
    if pythonpath:
        lines.append(f"export PYTHONPATH={shlex.quote(pythonpath)}")
    lines.append("exec " + " ".join(shlex.quote(part) for part in argv))
    lines.append("")
    return "\n".join(lines)


def windows_lnk_command(bat: Path, lnk: Path, icon: Path | None = None) -> list[str]:
    """PowerShell that creates a .lnk pointing at the .bat starter."""

    def ps(value: str) -> str:
        return "'" + str(value).replace("'", "''") + "'"

    icon_stmt = ""
    if icon is not None:
        icon_stmt = f"$shortcut.IconLocation = {ps(str(icon))}; "
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        f"$shortcut = $shell.CreateShortcut({ps(str(lnk))}); "
        f"$shortcut.TargetPath = {ps(str(bat))}; "
        f"{icon_stmt}"
        "$shortcut.Save()"
    )
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", script]


def plan_shortcuts(
    *,
    platform: str,
    python: str,
    pythonpath: str | None,
    directories: list[Path],
) -> list[PlannedShortcut]:
    planned: list[PlannedShortcut] = []
    for directory in directories:
        icon = application_icon("png")
        for slug, title, comment, args in SHORTCUT_SPECS:
            argv = command_argv(python, args)
            if platform == "windows":
                planned.append(
                    PlannedShortcut(directory / f"{slug}.bat", windows_bat(argv, pythonpath))
                )
            elif platform == "darwin":
                planned.append(
                    PlannedShortcut(
                        directory / f"{title}.command",
                        macos_command(argv, pythonpath),
                        executable=True,
                    )
                )
            else:
                planned.append(
                    PlannedShortcut(
                        directory / f"{slug}.desktop",
                        linux_desktop_entry(
                            title=title,
                            comment=comment,
                            argv=argv,
                            icon=icon,
                            pythonpath=pythonpath,
                        ),
                    )
                )
    return planned


def install_shortcuts(
    *,
    platform: str,
    python: str,
    pythonpath: str | None,
    directories: list[Path],
    create_windows_lnk: bool = True,
) -> list[Path]:
    written: list[Path] = []
    for item in plan_shortcuts(
        platform=platform,
        python=python,
        pythonpath=pythonpath,
        directories=directories,
    ):
        item.path.parent.mkdir(parents=True, exist_ok=True)
        item.path.write_text(item.content, encoding="utf-8", newline="\n")
        if item.executable:
            item.path.chmod(item.path.stat().st_mode | 0o755)
        written.append(item.path)
        if (
            create_windows_lnk
            and platform == "windows"
            and sys.platform.startswith("win")
            and item.path.suffix.lower() == ".bat"
        ):
            lnk = item.path.with_suffix(".lnk")
            ico = application_icon("ico")
            icon_path = Path(ico) if ico.endswith(".ico") else None
            subprocess.run(windows_lnk_command(item.path, lnk, icon_path), check=False)
            if lnk.is_file():
                written.append(lnk)
    return written


def run_shortcuts_cli(args: argparse.Namespace) -> int:
    platform = normalize_platform(getattr(args, "platform", None))
    python = getattr(args, "python", None) or sys.executable
    pythonpath = bundled_source_path()
    if getattr(args, "dest", None) is not None:
        directories = [Path(args.dest)]
    else:
        directories = default_directories(Path.home(), platform)
    planned = plan_shortcuts(
        platform=platform,
        python=python,
        pythonpath=pythonpath,
        directories=directories,
    )
    if getattr(args, "dry_run", False):
        for item in planned:
            print(item.path)
        return 0
    written = install_shortcuts(
        platform=platform,
        python=python,
        pythonpath=pythonpath,
        directories=directories,
    )
    print("Utworzono skróty:", flush=True)
    for path in written:
        print(path, flush=True)
    if platform == "linux":
        print(
            "Pozycje menu: ~/.local/share/applications. "
            "Na pulpicie może być potrzebne „Zezwól na uruchamianie”.",
            flush=True,
        )
    return 0
