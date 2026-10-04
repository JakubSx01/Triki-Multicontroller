"""Configurator draft shared by the desktop form and tests.

Saving goes through parse_settings, so the file stays the same
gui-settings.json. Live draft apply does not write the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from triki_controller.gui.settings import (
    PROFILE_NAMES,
    GuiSettings,
    default_thresholds,
    parse_settings,
)
from triki_controller.profiles.axis_map import DEFAULT_AXIS_MAP, resolve_axis_map

PROFILE_LABELS = {
    "steering": "Kierownica",
    "mouse": "AirMouse",
    "plane": "Joystick",
    "media": "Multimedia",
}

SOURCE_LABELS = {
    "pitch": "Pochylenie (pitch)",
    "roll": "Przechył (roll)",
    "yaw": "Obrót (yaw)",
    "off": "Wyłączone",
    "gyro_x": "Żyroskop X",
    "gyro_y": "Żyroskop Y",
    "gyro_z": "Żyroskop Z",
}
MOUSE_AXIS_LABELS = {
    "pitch": "Oś X (lewo/prawo)",
    "roll": "Oś Y (przód/tył)",
    "yaw": "Obrót (yaw)",
}

SIGN_CHOICES = (("Standardowy", 1.0), ("Odwrócony", -1.0))


def source_labels(profile: str) -> dict[str, str]:
    if profile in {"mouse", "plane"}:
        return {**SOURCE_LABELS, **MOUSE_AXIS_LABELS}
    return SOURCE_LABELS


@dataclass(frozen=True)
class MapField:
    key: str
    label: str
    choices: tuple[str, ...] | None


@dataclass(frozen=True)
class SliderField:
    key: str
    label: str
    low: float | None
    high: float | None
    step: float | None
    unit: str


MAP_FIELDS: dict[str, tuple[MapField, ...]] = {
    "steering": (
        MapField("wheel", "Oś kierownicy", ("pitch", "roll", "yaw")),
        MapField("wheel_sign", "Kierunek kierownicy", None),
        MapField("throttle", "Oś gazu", ("off", "pitch", "roll", "yaw")),
        MapField("throttle_sign", "Kierunek gazu", None),
        MapField("brake", "Oś hamulca", ("off", "pitch", "roll", "yaw")),
        MapField("brake_sign", "Kierunek hamulca", None),
    ),
    "mouse": (
        MapField("x", "Kursor lewo/prawo", ("pitch", "roll", "yaw")),
        MapField("y", "Kursor przód/tył", ("pitch", "roll", "yaw")),
    ),
    "plane": (
        MapField("x", "Lewo/prawo", ("pitch", "roll", "yaw")),
        MapField("y", "Przód/tył", ("pitch", "roll", "yaw")),
    ),
    "media": (
        MapField("volume", "Oś głośności", ("pitch", "roll", "yaw")),
        MapField("volume_sign", "Kierunek głośności", None),
    ),
}

SLIDER_FIELDS: dict[str, tuple[SliderField, ...]] = {
    "steering": (
        SliderField("deadzone_deg", "Strefa martwa kierownicy", 0.0, 60.0, 1.0, "°"),
        SliderField("full_scale_deg", "Pełny skręt", 5.0, 180.0, 1.0, "°"),
        SliderField("throttle_deadzone_deg", "Strefa martwa gazu", 0.0, 60.0, 1.0, "°"),
        SliderField("throttle_full_scale_deg", "Pełny gaz", 5.0, 180.0, 1.0, "°"),
        SliderField("brake_deadzone_deg", "Strefa martwa hamulca", 0.0, 60.0, 1.0, "°"),
        SliderField("brake_full_scale_deg", "Pełne hamowanie", 5.0, 180.0, 1.0, "°"),
    ),
    "mouse": (
        SliderField("deadzone_deg", "Strefa martwa pochylenia", 0.0, 60.0, 1.0, "°"),
        SliderField("full_scale_deg", "Pełne pochylenie", 5.0, 180.0, 1.0, "°"),
        SliderField("mouse_x_px_per_sec", "Prędkość X", 50.0, 8000.0, 50.0, "px/s"),
        SliderField("mouse_y_px_per_sec", "Prędkość Y", 50.0, 8000.0, 50.0, "px/s"),
        SliderField("mouse_x_sign", "Znak X", None, None, None, ""),
        SliderField("mouse_y_sign", "Znak Y", None, None, None, ""),
    ),
    "plane": (
        SliderField("deadzone_deg", "Strefa martwa", 0.0, 30.0, 1.0, "°"),
        SliderField("full_scale_deg", "Krawędź ekranu", 15.0, 180.0, 1.0, "°"),
        SliderField("mouse_x_sign", "Znak X", None, None, None, ""),
        SliderField("mouse_y_sign", "Znak Y", None, None, None, ""),
    ),
    "media": (
        SliderField("volume_tilt_deg", "Zakres głośności", 5.0, 360.0, 1.0, "°"),
        SliderField("click_window_s", "Okno wielokliku", 0.05, 2.0, 0.01, "s"),
        SliderField("invert_hold_s", "Czas odwrócenia", 0.02, 2.0, 0.01, "s"),
        SliderField(
            "player_cycle_timeout_s",
            "Przerwa między zmianą odtwarzacza",
            0.30,
            5.0,
            0.05,
            "s",
        ),
    ),
}


def resolved_draft(settings: GuiSettings) -> dict[str, object]:
    """Defaults filled in, so the form can edit every profile at once."""
    thresholds = {
        name: {
            **default_thresholds(name),
            **{key: float(value) for key, value in settings.thresholds.get(name, {}).items()},
        }
        for name in PROFILE_NAMES
    }
    axis_map = {
        name: dict(values) for name, values in resolve_axis_map(settings.axis_map).items()
    }
    return {
        "profile": settings.profile,
        "orientation": settings.orientation,
        "invert_pitch": settings.invert_pitch,
        "invert_roll": settings.invert_roll,
        "thresholds": thresholds,
        "axis_map": axis_map,
    }


def settings_from_draft(draft: Mapping[str, object], *, profile: str | None = None) -> GuiSettings:
    chosen = profile if profile is not None else str(draft["profile"])
    payload = {
        "schema_version": 1,
        "profile": chosen,
        "orientation": draft["orientation"],
        "invert_pitch": bool(draft["invert_pitch"]),
        "invert_roll": bool(draft["invert_roll"]),
        "thresholds": draft["thresholds"],
        "axis_map": draft["axis_map"],
    }
    return parse_settings(payload)


def default_profile_slice(name: str) -> tuple[dict[str, float], dict[str, str | float]]:
    return default_thresholds(name), dict(DEFAULT_AXIS_MAP[name])


def snap_step(value: float, step: float) -> float:
    if step <= 0:
        return float(value)
    snapped = round(float(value) / step) * step
    if step >= 1:
        return float(round(snapped))
    digits = max(0, len(f"{step:.6f}".rstrip("0").split(".")[-1]))
    return float(round(snapped, digits))
