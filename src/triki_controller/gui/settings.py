"""Versioned GUI settings: selected profile, mounting, axis signs, threshold overrides.

Live output and transport are never persisted; they always need an explicit click.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping
from triki_controller.gui.media_favorite import parse_media_favorite

from triki_controller.motion.orientation import (
    DEFAULT_ORIENTATION,
    ORIENTATION_IDS,
    parse_orientation,
)
from triki_controller.profiles.axis_map import parse_axis_map
from triki_controller.profiles.control_bindings import parse_control_bindings
from triki_controller.profiles.builtin import PROFILE_LIMITS, profile_by_name, with_overrides

SETTINGS_SCHEMA_VERSION = 1
PROFILE_NAMES = ("steering", "mouse", "plane", "media")
THRESHOLD_FIELDS = (
    "deadzone_deg",
    "full_scale_deg",
    "brake_deadzone_deg",
    "brake_full_scale_deg",
    "throttle_deadzone_deg",
    "throttle_full_scale_deg",
    "mouse_px_per_sec",
    "mouse_x_px_per_sec",
    "mouse_y_px_per_sec",
    "mouse_x_sign",
    "mouse_y_sign",
    "volume_tilt_deg",
    "volume_repeat_s",
    "click_window_s",
    "invert_hold_s",
    "player_cycle_timeout_s",
)
# Fields accepted from older JSON that are migrated into independent X/Y rates.
_LEGACY_RATE_FIELD = "mouse_px_per_sec"
_TOP_LEVEL = {
    "schema_version",
    "profile",
    "orientation",
    "invert_pitch",
    "invert_roll",
    "thresholds",
    "axis_map",
    "media_gestures_enabled",
    "media_player",
    "media_favorite",
    "control_bindings",
}


class SettingsError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class GuiSettings:
    profile: str = "steering"
    orientation: str = DEFAULT_ORIENTATION
    invert_pitch: bool = False
    invert_roll: bool = False
    thresholds: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    axis_map: Mapping[str, Mapping[str, str | float]] = field(default_factory=dict)

    media_gestures_enabled: bool = True
    media_player: str | None = None
    control_bindings: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    media_favorite: Mapping[str, str] | None = None

    def to_json(self) -> dict[str, object]:
        return {
            "media_gestures_enabled": self.media_gestures_enabled,
            "media_player": self.media_player,
            "media_favorite": parse_media_favorite(self.media_favorite),
            "control_bindings": parse_control_bindings(self.control_bindings),
            "schema_version": SETTINGS_SCHEMA_VERSION,
            "profile": self.profile,
            "orientation": self.orientation,
            "invert_pitch": self.invert_pitch,
            "invert_roll": self.invert_roll,
            "thresholds": {
                name: {key: float(value) for key, value in values.items()}
                for name, values in self.thresholds.items()
            },
            "axis_map": {
                name: dict(values) for name, values in self.axis_map.items()
            },
        }


def default_settings_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "triki-controller" / "gui-settings.json"


def default_thresholds(name: str) -> dict[str, float]:
    profile = profile_by_name(name)
    return {key: float(getattr(profile, key)) for key in THRESHOLD_FIELDS}


def parse_settings(data: object) -> GuiSettings:
    if not isinstance(data, dict):
        raise SettingsError(["settings must be a JSON object"])
    errors: list[str] = []
    unknown = sorted(set(data) - _TOP_LEVEL)
    if unknown:
        errors.append(f"unknown fields: {', '.join(unknown)}")
    version = data.get("schema_version")
    if version != SETTINGS_SCHEMA_VERSION or isinstance(version, bool):
        errors.append(f"schema_version must be {SETTINGS_SCHEMA_VERSION}, got {version!r}")
    profile = data.get("profile", "steering")
    if profile not in PROFILE_NAMES:
        errors.append(f"profile: unknown {profile!r}")
    orientation_raw = data.get("orientation", DEFAULT_ORIENTATION)
    orientation = DEFAULT_ORIENTATION
    if not isinstance(orientation_raw, str):
        errors.append(f"orientation: must be a string, got {orientation_raw!r}")
    else:
        try:
            orientation = parse_orientation(orientation_raw)
        except ValueError:
            errors.append(
                f"orientation: unknown {orientation_raw!r}; "
                f"choose one of: {', '.join(ORIENTATION_IDS)}"
            )
    flags: dict[str, bool] = {}
    for key in ("invert_pitch", "invert_roll"):
        value = data.get(key, False)
        if not isinstance(value, bool):
            errors.append(f"{key}: must be true or false")
        flags[key] = bool(value)
    thresholds = _parse_thresholds(data.get("thresholds", {}), errors)
    axis_map = parse_axis_map(data.get("axis_map", {}), errors)
    enabled = data.get("media_gestures_enabled", True)
    if not isinstance(enabled, bool):
        errors.append("media_gestures_enabled: must be true or false")
    player = data.get("media_player")
    if player is not None and (not isinstance(player, str) or not player.strip()):
        errors.append("media_player: must be a nonempty string or null")
    bindings = parse_control_bindings(data.get("control_bindings", {}), errors)
    favorite = None
    try:
        favorite = parse_media_favorite(data.get("media_favorite"))
    except ValueError as exc:
        errors.append(str(exc))
    if errors:
        raise SettingsError(errors)
    return GuiSettings(
        profile=str(profile),
        orientation=orientation,
        invert_pitch=flags["invert_pitch"],
        invert_roll=flags["invert_roll"],
        thresholds=thresholds,
        axis_map=axis_map,
        media_gestures_enabled=enabled,
        media_player=player,
        control_bindings=bindings,
        media_favorite=favorite,
    )


def _migrate_legacy_rates(parsed: dict[str, float]) -> dict[str, float]:
    """Old JSON may only store mouse_px_per_sec; copy into independent X/Y if absent."""
    if _LEGACY_RATE_FIELD not in parsed:
        return parsed
    rate = parsed[_LEGACY_RATE_FIELD]
    if "mouse_x_px_per_sec" not in parsed:
        parsed["mouse_x_px_per_sec"] = rate
    if "mouse_y_px_per_sec" not in parsed:
        parsed["mouse_y_px_per_sec"] = rate
    return parsed


def _parse_thresholds(raw: object, errors: list[str]) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict):
        errors.append("thresholds: must be an object keyed by profile")
        return {}
    result: dict[str, dict[str, float]] = {}
    for name, values in raw.items():
        if name not in PROFILE_NAMES:
            errors.append(f"thresholds: unknown profile {name!r}")
            continue
        if not isinstance(values, dict):
            errors.append(f"thresholds.{name}: must be an object")
            continue
        parsed: dict[str, float] = {}
        for key, value in values.items():
            where = f"thresholds.{name}.{key}"
            if key not in THRESHOLD_FIELDS:
                errors.append(f"{where}: unknown field")
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                errors.append(f"{where}: must be a number")
                continue
            if not math.isfinite(value):
                errors.append(f"{where}: must be finite")
                continue
            if key in PROFILE_LIMITS:
                low, high = PROFILE_LIMITS[key]
                if not (low <= float(value) <= high):
                    errors.append(f"{where}: must be in [{low}, {high}]")
                    continue
            if key in ("mouse_x_sign", "mouse_y_sign") and float(value) not in (1.0, -1.0):
                errors.append(f"{where}: must be +1 or -1")
                continue
            parsed[key] = float(value)
        parsed = _migrate_legacy_rates(parsed)
        try:
            with_overrides(profile_by_name(name), **parsed)
        except ValueError as exc:
            errors.append(f"thresholds.{name}: {exc}")
            continue
        result[name] = parsed
    return result


def load_settings(path: Path | None = None) -> GuiSettings | None:
    path = path or default_settings_path()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SettingsError([f"invalid JSON: {exc}"]) from exc
    return parse_settings(data)


def save_settings(settings: GuiSettings, path: Path | None = None) -> Path:
    path = path or default_settings_path()
    parse_settings(settings.to_json())
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(settings.to_json(), indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path
