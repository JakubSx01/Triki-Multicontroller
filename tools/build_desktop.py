#!/usr/bin/env python3
"""Native PyInstaller desktop build. Does not edit project/application configs."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAME = "TrikiController"


def asset_manifest(root: Path = ROOT) -> list[tuple[Path, str]]:
    """Preserve package-relative paths, including nested fonts/images/licenses."""
    package = root / "src" / "triki_controller"
    return [(p, str(p.parent.relative_to(root / "src")))
            for p in sorted(package.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts
            and p.suffix not in (".py", ".pyc", ".pyo")]


def build_command(root: Path = ROOT, target: str | None = None, console: bool = False) -> list[str]:
    target = target or sys.platform
    if target != sys.platform:
        raise ValueError("PyInstaller is not a cross-compiler: build on the target OS")
    if target not in ("linux", "darwin", "win32"):
        raise ValueError(f"Unsupported native platform {target}")
    output = root / "packaging"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--noupx",
           "--name", NAME, "--distpath", str(output / "dist"),
           "--workpath", str(output / "build"), "--specpath", str(output / "build"),
           "--paths", str(root / "src"), "--paths", str(output),
           "--collect-all", "customtkinter", "--collect-all", "PIL",
           "--collect-submodules", "bleak", "--collect-submodules", "pystray",
           "--collect-submodules", "triki_controller", "--hidden-import", "desktop_shortcuts"]
    if target == "linux":
        cmd += ["--collect-all", "evdev", "--collect-all", "pywayland"]
    elif not console:
        cmd.append("--windowed")
    if target == "darwin":
        cmd += ["--osx-bundle-identifier", "com.homelabpowered.triki-controller"]
    sep = ";" if target == "win32" else ":"
    for path, destination in asset_manifest(root):
        cmd += ["--add-data", f"{path}{sep}{destination}"]
    for filename in ("README.md", "THIRD_PARTY_NOTICES.md"):
        if (root / filename).is_file():
            cmd += ["--add-data", f"{root / filename}{sep}licenses"]
    icons = root / "src" / "triki_controller" / "gui" / "assets" / "app_icon"
    icon_name = {"win32": "triki-controller.ico", "darwin": "triki-controller.icns"}.get(target)
    if icon_name and (icons / icon_name).is_file():
        # Linux has no bootloader icon slot; .desktop files point at the PNG.
        cmd += ["--icon", str(icons / icon_name)]
    cmd.append(str(output / "desktop_entry.py"))
    return cmd


def artifact_path(root: Path = ROOT, target: str | None = None, console: bool = False) -> Path:
    target = target or sys.platform
    base = root / "packaging" / "dist"
    if target == "darwin" and not console:
        return base / f"{NAME}.app" / "Contents" / "MacOS" / NAME
    return base / NAME / (NAME + (".exe" if target == "win32" else ""))


def create_archive(artifact: Path, target: str | None = None) -> Path:
    """Archive the whole bundle, never just its bootloader executable."""
    target = target or sys.platform
    import tarfile
    import zipfile
    bundle = artifact.parent
    if target == "darwin" and artifact.parent.name == "MacOS":
        bundle = artifact.parents[2]
    archive = ROOT / "packaging/dist" / f"{NAME}-{target}-{platform.machine()}"
    if target == "linux":
        archive = archive.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz") as output:
            output.add(bundle, arcname=bundle.name)
    elif target == "darwin":
        archive = archive.with_suffix(".zip")
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(archive)], check=True)
    else:
        archive = archive.with_suffix(".zip")
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as output:
            for path in sorted(bundle.rglob("*")):
                if path.is_file():
                    output.write(path, path.relative_to(bundle.parent))
    return archive


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("linux", "win32", "darwin"), default=sys.platform)
    parser.add_argument("--console", action="store_true", help="Retain stdout on Windows/macOS for smoke")
    parser.add_argument("--smoke", action="store_true", help="Run actual fake+dry-run GUI smoke; requires a display")
    parser.add_argument("--command-only", action="store_true", help="Print command without building/writing")
    args = parser.parse_args(argv)
    try:
        command = build_command(target=args.target, console=args.console)
    except ValueError as exc:
        parser.error(str(exc))
    if args.command_only:
        print(json.dumps(command, indent=2))
        return 0
    required = ["PyInstaller", "customtkinter", "PIL", "bleak", "pystray", "tkinter"]
    if args.target == "linux":
        required += ["evdev", "pywayland"]
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        parser.error("Missing build dependencies: " + ", ".join(missing) + "; see docs/desktop-distribution.md")
    build = ROOT / "packaging" / "build"
    build.mkdir(parents=True, exist_ok=True)
    with (build / "pyinstaller.log").open("w", encoding="utf-8") as log:
        completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if completed.returncode:
        print(f"Build failed; real log: {build / 'pyinstaller.log'}", file=sys.stderr)
        return completed.returncode
    artifact = artifact_path(console=args.console)
    if not artifact.is_file():
        raise RuntimeError(f"PyInstaller did not produce {artifact}")
    report = {"platform": sys.platform, "machine": platform.machine(), "python": sys.version,
              "artifact": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
              "command": command, "assets": [[str(p), dest] for p, dest in asset_manifest()],
              "smoke_exit_code": None}
    if args.smoke:
        with (build / "smoke.log").open("w", encoding="utf-8") as log:
            completed = subprocess.run([str(artifact), "--smoke"], cwd=artifact.parent,
                                       stdout=log, stderr=subprocess.STDOUT, timeout=40)
        report["smoke_exit_code"] = completed.returncode
    if report["smoke_exit_code"] in (None, 0):
        archive = create_archive(artifact)
        report["archive"] = str(archive)
        report["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    (build / "build-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(report["smoke_exit_code"] or 0)


if __name__ == "__main__":
    raise SystemExit(main())
