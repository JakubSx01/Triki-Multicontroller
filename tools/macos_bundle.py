"""Prepare generated macOS bundle metadata before PyInstaller signs it."""
from __future__ import annotations

import ast
from pathlib import Path
import plistlib

APPLE_EVENTS_USAGE = (
    "Triki Controller uses Apple Events to control playback in Music and Spotify "
    "when you use controller media actions."
)
ENTITLEMENTS = {"com.apple.security.automation.apple-events": True}


def makespec_command(command: list[str]) -> list[str]:
    if command[1:3] != ["-m", "PyInstaller"]:
        raise ValueError("Expected a python -m PyInstaller build command")
    result = [command[0], "-m", "PyInstaller.utils.cliutils.makespec"]
    args = iter(command[3:])
    for arg in args:
        if arg in ("--noconfirm", "--clean"):
            continue
        if arg in ("--distpath", "--workpath"):
            if next(args, None) is None:
                raise ValueError(f"Missing value for {arg}")
            continue
        result.append(arg)
    return result


def inject_bundle_metadata(spec: Path) -> dict:
    """Reject unfamiliar spec shapes rather than silently omit privacy metadata."""
    tree = ast.parse(spec.read_text(encoding="utf-8"))
    bundles = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Name) and node.func.id == "BUNDLE"]
    if len(bundles) != 1:
        raise ValueError(f"Expected exactly one BUNDLE in {spec}; found {len(bundles)}")
    bundle = bundles[0]
    if any(keyword.arg is None for keyword in bundle.keywords):
        raise ValueError("BUNDLE **kwargs cannot be safely merged")
    keywords = [keyword for keyword in bundle.keywords if keyword.arg == "info_plist"]
    if len(keywords) > 1:
        raise ValueError("Duplicate BUNDLE info_plist")
    info = {}
    if keywords:
        try:
            info = ast.literal_eval(keywords[0].value)
        except (ValueError, TypeError) as exc:
            raise ValueError("BUNDLE info_plist must be a literal dictionary or None") from exc
        if info is None:
            info = {}
        if not isinstance(info, dict):
            raise ValueError("BUNDLE info_plist must be a dictionary or None")
    info.setdefault("NSAppleEventsUsageDescription", APPLE_EVENTS_USAGE)
    usage = info["NSAppleEventsUsageDescription"]
    if not isinstance(usage, str) or not usage.strip():
        raise ValueError("BUNDLE NSAppleEventsUsageDescription must be nonempty text")
    # Validate plist compatibility before changing even the generated spec.
    plistlib.dumps(info)
    value = ast.parse(repr(info), mode="eval").body
    if keywords:
        keywords[0].value = value
    else:
        bundle.keywords.append(ast.keyword(arg="info_plist", value=value))
    ast.fix_missing_locations(tree)
    updated = ast.unparse(tree) + "\n"
    compile(updated, str(spec), "exec")
    spec.write_text(updated, encoding="utf-8")
    return info


def verify_bundle_metadata(bundle: Path, expected: dict) -> None:
    """Read the final plist without altering a potentially signed bundle."""
    path = bundle / "Contents" / "Info.plist"
    with path.open("rb") as source:
        info = plistlib.load(source)
    for key, value in expected.items():
        if key not in info or info[key] != value:
            raise ValueError(f"Final bundle Info.plist missing or changed {key}: {path}")


def write_entitlements(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(ENTITLEMENTS, sort_keys=True))


def spec_build_command(command: list[str], spec: Path) -> list[str]:
    """Only execution options remain valid when building an existing spec."""
    return [command[0], "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", command[command.index("--distpath") + 1],
            "--workpath", command[command.index("--workpath") + 1], str(spec)]
