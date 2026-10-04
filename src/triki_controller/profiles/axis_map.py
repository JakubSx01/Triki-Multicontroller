"""Per-profile axis source selection.

Defaults reproduce the built-in steering, mouse, and media mapping.
Missing keys keep those defaults. Accel channels stay diagnostic-only:
profiles consume tilt (degrees) and gyro rate, not raw accelerometer counts.
"""

from __future__ import annotations

from typing import Mapping

TILT_SOURCES = ("pitch", "roll", "yaw")
BRAKE_SOURCES = ("pitch", "roll", "yaw", "off")

# Signs are the extra flip applied after the profile invert flags.
# Steering: wheel = -(yaw * roll_sign). Throttle and brake share pitch.
# Negative pitch (forward tip on the vertical mount) is gas; positive is brake.
DEFAULT_AXIS_MAP: dict[str, dict[str, str | float]] = {
    "steering": {
        "wheel": "roll",
        "wheel_sign": -1.0,
        "throttle": "pitch",
        "throttle_sign": 1.0,
        "brake": "pitch",
        "brake_sign": 1.0,
    },
    "mouse": {
        # Device X (pitch / accel X) is left-right. Device Y (roll / accel Y) is front-back.
        "x": "pitch",
        "y": "roll",
    },
    "plane": {
        # Held tilt, same axes as AirMouse. Level is center; the angle stays.
        "x": "pitch",
        "y": "roll",
    },
    "media": {
        "volume": "yaw",
        "volume_sign": 1.0,
    },
}

_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "steering": {
        "wheel": TILT_SOURCES,
        "throttle": BRAKE_SOURCES,
        "brake": BRAKE_SOURCES,
    },
    "mouse": {
        "x": TILT_SOURCES,
        "y": TILT_SOURCES,
    },
    "plane": {
        "x": TILT_SOURCES,
        "y": TILT_SOURCES,
    },
    "media": {
        "volume": TILT_SOURCES,
    },
}
_SIGNS = {
    "steering": ("wheel_sign", "throttle_sign", "brake_sign"),
    "mouse": (),
    "plane": (),
    "media": ("volume_sign",),
}


def _migrate_gyro_mouse(raw: dict[str, object]) -> dict[str, object]:
    """Old AirMouse axis map was gyro rate. The cursor now follows tilt X/Y."""
    mouse = raw.get("mouse")
    if not isinstance(mouse, dict):
        return raw
    if not any(
        isinstance(mouse.get(key), str) and str(mouse.get(key)).startswith("gyro_")
        for key in ("x", "y")
    ):
        return raw
    migrated = dict(raw)
    mouse_tilt = dict(mouse)
    mouse_tilt["x"] = "pitch"
    mouse_tilt["y"] = "roll"
    migrated["mouse"] = mouse_tilt
    return migrated


def _migrate_gyro_plane(raw: dict[str, object]) -> dict[str, object]:
    """Joystick used to be a gyro-rate stick, which sprang back to center."""
    plane = raw.get("plane")
    if not isinstance(plane, dict):
        return raw
    if not any(
        isinstance(plane.get(key), str) and str(plane.get(key)).startswith("gyro_")
        for key in ("x", "y")
    ):
        return raw
    migrated = dict(raw)
    plane_tilt = dict(plane)
    plane_tilt["x"] = "pitch"
    plane_tilt["y"] = "roll"
    migrated["plane"] = plane_tilt
    return migrated


def resolve_axis_map(
    stored: Mapping[str, Mapping[str, object]] | None,
) -> dict[str, dict[str, str | float]]:
    """Fill omitted keys with DEFAULT_AXIS_MAP. Unknown profiles are ignored."""
    stored = stored or {}
    resolved: dict[str, dict[str, str | float]] = {}
    for name, defaults in DEFAULT_AXIS_MAP.items():
        overlay = stored.get(name, {})
        merged: dict[str, str | float] = dict(defaults)
        if isinstance(overlay, Mapping):
            for key, value in overlay.items():
                if key in defaults:
                    merged[key] = value  # type: ignore[assignment]
        resolved[name] = merged
    return resolved


def parse_axis_map(raw: object, errors: list[str]) -> dict[str, dict[str, str | float]]:
    """Validate a settings overlay. Only provided keys are returned."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        errors.append("axis_map: must be an object keyed by profile")
        return {}
    raw = _migrate_gyro_plane(_migrate_gyro_mouse(raw))
    result: dict[str, dict[str, str | float]] = {}
    for name, values in raw.items():
        where = f"axis_map.{name}"
        if name not in DEFAULT_AXIS_MAP:
            errors.append(f"{where}: unknown profile")
            continue
        if not isinstance(values, dict):
            errors.append(f"{where}: must be an object")
            continue
        parsed: dict[str, str | float] = {}
        allowed = set(_FIELDS[name]) | set(_SIGNS[name])
        for key, value in values.items():
            field = f"{where}.{key}"
            if key not in allowed:
                errors.append(f"{field}: unknown field")
                continue
            if key in _SIGNS[name]:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    errors.append(f"{field}: must be +1 or -1")
                    continue
                if float(value) not in (1.0, -1.0):
                    errors.append(f"{field}: must be +1 or -1")
                    continue
                parsed[key] = float(value)
                continue
            choices = _FIELDS[name][key]
            if not isinstance(value, str) or value not in choices:
                errors.append(f"{field}: must be one of: {', '.join(choices)}")
                continue
            parsed[key] = value
        result[name] = parsed
    return result
