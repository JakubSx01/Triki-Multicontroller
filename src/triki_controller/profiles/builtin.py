"""Built-in logical profiles. Thresholds live here, not in the BLE path."""

from __future__ import annotations

from dataclasses import dataclass, replace

# Explicit safe limits for every tunable numeric field (inclusive).
# deadzone must still be strictly less than its matching full_scale.
PROFILE_LIMITS: dict[str, tuple[float, float]] = {
    "deadzone_deg": (0.0, 60.0),
    "full_scale_deg": (5.0, 180.0),
    "brake_deadzone_deg": (0.0, 60.0),
    "brake_full_scale_deg": (5.0, 180.0),
    "throttle_deadzone_deg": (0.0, 60.0),
    "throttle_full_scale_deg": (5.0, 180.0),
    "mouse_px_per_sec": (50.0, 8_000.0),
    "mouse_x_px_per_sec": (50.0, 8_000.0),
    "mouse_y_px_per_sec": (50.0, 8_000.0),
    "volume_tilt_deg": (5.0, 360.0),
    "volume_repeat_s": (0.02, 2.0),
    "click_window_s": (0.05, 2.0),
    "invert_hold_s": (0.02, 2.0),
    "player_cycle_timeout_s": (0.30, 5.0),
}


@dataclass(frozen=True, slots=True)
class Profile:
    id: str
    revision: str
    mode: str
    deadzone_deg: float
    full_scale_deg: float
    brake_deadzone_deg: float
    brake_full_scale_deg: float
    throttle_deadzone_deg: float
    throttle_full_scale_deg: float
    mouse_px_per_sec: float
    mouse_x_px_per_sec: float
    mouse_y_px_per_sec: float
    mouse_x_sign: float
    mouse_y_sign: float
    volume_tilt_deg: float
    volume_repeat_s: float
    click_window_s: float
    invert_hold_s: float
    player_cycle_timeout_s: float
    pitch_sign: float = 1.0
    roll_sign: float = 1.0

    def validated(self) -> Profile:
        if self.mode not in {"steering", "mouse", "plane", "media"}:
            raise ValueError(f"unsupported profile mode {self.mode!r}")
        values = {
            "deadzone_deg": self.deadzone_deg,
            "full_scale_deg": self.full_scale_deg,
            "brake_deadzone_deg": self.brake_deadzone_deg,
            "brake_full_scale_deg": self.brake_full_scale_deg,
            "throttle_deadzone_deg": self.throttle_deadzone_deg,
            "throttle_full_scale_deg": self.throttle_full_scale_deg,
            "mouse_px_per_sec": self.mouse_px_per_sec,
            "mouse_x_px_per_sec": self.mouse_x_px_per_sec,
            "mouse_y_px_per_sec": self.mouse_y_px_per_sec,
            "volume_tilt_deg": self.volume_tilt_deg,
            "volume_repeat_s": self.volume_repeat_s,
            "click_window_s": self.click_window_s,
            "invert_hold_s": self.invert_hold_s,
            "player_cycle_timeout_s": self.player_cycle_timeout_s,
        }
        for name, value in values.items():
            _require_finite_number(value, name)
            low, high = PROFILE_LIMITS[name]
            if not (low <= float(value) <= high):
                raise ValueError(f"{name} must be in [{low}, {high}]")
        if self.deadzone_deg >= self.full_scale_deg:
            raise ValueError("deadzone_deg must be less than full_scale_deg")
        if self.brake_deadzone_deg >= self.brake_full_scale_deg:
            raise ValueError("brake_deadzone_deg must be less than brake_full_scale_deg")
        if self.throttle_deadzone_deg >= self.throttle_full_scale_deg:
            raise ValueError("throttle_deadzone_deg must be less than throttle_full_scale_deg")
        for name, value in (
            ("mouse_x_sign", self.mouse_x_sign),
            ("mouse_y_sign", self.mouse_y_sign),
            ("pitch_sign", self.pitch_sign),
            ("roll_sign", self.roll_sign),
        ):
            _require_finite_number(value, name)
            if float(value) not in (1.0, -1.0):
                raise ValueError(f"{name} must be +1 or -1")
        return self


def math_finite(value: float) -> bool:
    return value == value and abs(value) != float("inf")


def _require_finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not math_finite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _base(**kwargs: float | str) -> Profile:
    data: dict[str, float | str] = {
        "revision": "builtin-1",
        "deadzone_deg": 5.0,
        "full_scale_deg": 40.0,
        "brake_deadzone_deg": 6.0,
        "brake_full_scale_deg": 45.0,
        "throttle_deadzone_deg": 6.0,
        "throttle_full_scale_deg": 45.0,
        "mouse_px_per_sec": 900.0,
        "mouse_x_px_per_sec": 900.0,
        "mouse_y_px_per_sec": 900.0,
        "mouse_x_sign": 1.0,
        "mouse_y_sign": 1.0,
        "volume_tilt_deg": 18.0,
        "volume_repeat_s": 0.18,
        "click_window_s": 0.40,
        "invert_hold_s": 0.12,
        "player_cycle_timeout_s": 2.0,
    }
    data.update(kwargs)
    return Profile(**data).validated()  # type: ignore[arg-type]


def steering_profile(*, invert_pitch: bool = False, invert_roll: bool = False) -> Profile:
    return _base(
        id="steering",
        revision="builtin-4-saved-pedals",
        mode="steering",
        # Wheel range/deadzone. Saved working setup: full lock at 90°.
        deadzone_deg=10.0,
        full_scale_deg=90.0,
        # Pedals share pitch. Gas and brake each have their own range.
        brake_deadzone_deg=8.0,
        brake_full_scale_deg=40.0,
        throttle_deadzone_deg=8.0,
        throttle_full_scale_deg=40.0,
        pitch_sign=-1.0 if invert_pitch else 1.0,
        roll_sign=-1.0 if invert_roll else 1.0,
    )


def mouse_profile(*, invert_pitch: bool = False, invert_roll: bool = False) -> Profile:
    return _base(
        id="mouse",
        revision="builtin-5-deadzone-10",
        mode="mouse",
        # Saved AirMouse defaults: tilt degrees for a full cursor speed.
        # Signs stay +1 so device X moves the cursor left/right and device Y front/back.
        deadzone_deg=10.0,
        full_scale_deg=100.0,
        mouse_px_per_sec=1400.0,
        mouse_x_px_per_sec=1400.0,
        mouse_y_px_per_sec=1400.0,
        pitch_sign=-1.0 if invert_pitch else 1.0,
        roll_sign=-1.0 if invert_roll else 1.0,
    )


def plane_profile(*, invert_pitch: bool = False, invert_roll: bool = False) -> Profile:
    """Flight stick from held tilt. 45° is about halfway to the screen edge."""
    return _base(
        id="plane",
        revision="builtin-2-tilt-stick",
        mode="plane",
        deadzone_deg=6.0,
        full_scale_deg=90.0,
        mouse_px_per_sec=1400.0,
        mouse_x_px_per_sec=1400.0,
        mouse_y_px_per_sec=1400.0,
        pitch_sign=-1.0 if invert_pitch else 1.0,
        roll_sign=-1.0 if invert_roll else 1.0,
    )


def media_profile(*, invert_pitch: bool = False, invert_roll: bool = False) -> Profile:
    return _base(
        id="media",
        mode="media",
        # Saved multimedia defaults.
        volume_tilt_deg=40.0,
        click_window_s=0.40,
        invert_hold_s=0.11,
        player_cycle_timeout_s=1.55,
        pitch_sign=-1.0 if invert_pitch else 1.0,
        roll_sign=-1.0 if invert_roll else 1.0,
    )


def profile_by_name(name: str, *, invert_pitch: bool = False, invert_roll: bool = False) -> Profile:
    builders = {
        "steering": steering_profile,
        "mouse": mouse_profile,
        "plane": plane_profile,
        "media": media_profile,
    }
    try:
        build = builders[name]
    except KeyError as exc:
        raise ValueError(f"unknown profile {name!r}") from exc
    return build(invert_pitch=invert_pitch, invert_roll=invert_roll)


def with_overrides(profile: Profile, **changes: float) -> Profile:
    return replace(profile, **changes).validated()
