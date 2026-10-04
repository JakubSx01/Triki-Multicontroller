"""Map gravity-relative tilt onto steering, mouse, joystick, or media controls.

Logical names only. Linux event codes stay in the output backend.
Steering is the vertical mount: roll is the wheel, a forward tip (negative
pitch) is gas, and a tip back is brake. Gas and brake have separate ranges.
Mouse and joystick stay horizontal. Device X (pitch) is left/right and device
Y (roll) is front/back. Mouse speed follows the tilt; the joystick holds it.
Media volume is a yaw knob on the horizontal mount.
"""

from __future__ import annotations

import math
from typing import Mapping

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    MotionSample,
    PipelineStageStatus,
)
from triki_controller.profiles.axis_map import resolve_axis_map
from triki_controller.profiles.builtin import Profile
from triki_controller.profiles.control_bindings import KEY_ACTIONS, parse_control_bindings

_INVERT_ENTER = -0.50
_INVERT_EXIT = 0.45
_MOUSE_GAP_S = 0.20
# Media always uses the horizontal mounting frame (no GUI override).
MEDIA_ORIENTATION = "horizontal"
# Steering is held upright; twist around vertical = wheel (no GUI override).
STEERING_ORIENTATION = "vertical"
# Mouse tilt-mouse stays flat on the table / horizontal mount.
MOUSE_ORIENTATION = "horizontal"
# Ignore tiny yaw jitter; larger moves change volume immediately.
_YAW_NOISE_MIN_DEG = 0.4
_YAW_NOISE_FRAC = 0.08
# Volume only while the cap is near face-up or face-down. cos(32°) ≈ 0.85.
_LEVEL_ALIGN = 0.85
# One sample larger than this is a flip glitch, not a twist.
_YAW_STEP_MAX_DEG = 45.0

_MEDIA_CLICKS = {1: "play_pause", 2: "next_track", 3: "previous_track"}
_MOUSE_CLICKS = {1: "mouse_left", 2: "mouse_right"}
# Shake on gyro X/Y only. Yaw (Z) is the volume twist and must not cycle players.
_SHAKE_XY_DPS = 200.0
_SHAKE_MIN_SAMPLES = 5


def _norm_deg(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def _shaped(angle_deg: float, deadzone: float, full_scale: float) -> float:
    magnitude = abs(angle_deg)
    if magnitude <= deadzone:
        return 0.0
    span = full_scale - deadzone
    return math.copysign(min(1.0, (magnitude - deadzone) / span), angle_deg)


def _shaped_ease(angle_deg: float, deadzone: float, full_scale: float, power: float) -> float:
    """Same as _shaped, then ease-in so small leans barely move the axis."""
    value = _shaped(angle_deg, deadzone, full_scale)
    if value == 0.0 or power <= 1.0:
        return value
    return math.copysign(abs(value) ** power, value)


# Pedals ease independently of wheel; full_scale/deadzone come from Profile.
_PEDAL_EASE = 1.45
_WHEEL_EASE = 1.2


def _neutral(sample: MotionSample, profile: Profile, epoch: int = 0) -> MappedState:
    return MappedState(
        schema_version=SCHEMA_VERSION,
        raw_session_id=sample.raw_session_id,
        raw_connection_epoch=sample.raw_connection_epoch,
        raw_sample_seq=sample.raw_sample_seq,
        profile_id=profile.id,
        profile_revision=profile.revision,
        activation_epoch=epoch,
        held_buttons=(),
        held_keys=(),
        absolute_axes={},
        relative_deltas={},
        stage_status=PipelineStageStatus.AVAILABLE,
        pulses=(),
    )


def _tilt_deg(sample: MotionSample, source: str, profile: Profile, sign: float) -> float | None:
    """Signed tilt channel. ``off`` is a resting pedal. None if that channel is missing."""
    if source == "off":
        return 0.0
    raw = {
        "pitch": sample.tilt_pitch_deg,
        "roll": sample.tilt_roll_deg,
        "yaw": sample.tilt_yaw_deg,
    }[source]
    if raw is None:
        return None
    axis_sign = profile.pitch_sign if source == "pitch" else profile.roll_sign
    return float(raw) * axis_sign * sign


class DeviceProfileMapper:
    def __init__(self) -> None:
        self._axis_map: dict[str, dict[str, str | float]] = {}
        self._control_bindings: dict[str, dict[str, str]] = {}
        self._media_gestures_enabled = True
        self._active_profile: tuple[str, str, str] | None = None
        self._active_directions: set[str] = set()
        self._down = False
        self._clicks = 0
        self._last_release_ns: int | None = None
        self._click_names: dict[int, str | None] = dict(_MEDIA_CLICKS)
        self._volume = 0.5
        self._system_offset = 0.0
        self._system_active = False
        self._prev_yaw: float | None = None
        self._inverted = False
        self._invert_since_ns: int | None = None
        self._upright_since_ns: int | None = None
        self._shake_run = 0
        self._shake_last_ns: int | None = None
        self._shake_quiet = True

    def set_axis_map(self, axis_map: Mapping[str, Mapping[str, object]] | None) -> None:
        """Replace the source overlay. Omitted keys keep the built-in defaults."""
        stored = axis_map or {}
        self._axis_map = {
            name: dict(values) for name, values in stored.items() if isinstance(values, Mapping)
        }

    def set_media_gestures_enabled(self, enabled: bool) -> None:
        """Enable only shake-to-cycle; mute, transport and volume stay active."""
        if not isinstance(enabled, bool):
            raise ValueError("media_gestures_enabled must be a bool")
        self._media_gestures_enabled = enabled
        self._shake_run = 0
        self._shake_last_ns = None
        self._shake_quiet = True

    def set_control_bindings(self, mapping: Mapping[str, Mapping[str, str]] | None) -> None:
        """Replace a validated sparse logical overlay, discarding old held/click state."""
        parsed = parse_control_bindings({} if mapping is None else mapping)
        self._control_bindings = parsed
        self.reset()

    def reset(self) -> None:
        """Clear transient state, retaining all configured mappings and toggles."""
        self._active_profile = None
        self._active_directions.clear()
        self._down = False
        self._clicks = 0
        self._last_release_ns = None
        self._click_names = dict(_MEDIA_CLICKS)
        self._volume = 0.5
        self._system_offset = 0.0
        self._system_active = False
        self._prev_yaw = None
        self._inverted = False
        self._invert_since_ns = None
        self._upright_since_ns = None
        self._shake_run = 0
        self._shake_last_ns = None
        self._shake_quiet = True

    def set_media_baseline(self, volume: float) -> None:
        """Start volume at connect/recenter. Further twists move 0–100% from here."""
        if not math.isfinite(volume):
            return
        self._volume = max(0.0, min(1.0, float(volume)))
        self._prev_yaw = None

    def take_pending_click(self) -> str | None:
        """Commit a click sequence that has not yet reached the quiet window."""
        if self._inverted or self._down or self._clicks <= 0:
            self._clicks = 0
            self._last_release_ns = None
            return None
        fallback = next(iter(self._click_names.values()))
        name = self._click_names.get(self._clicks, fallback)
        self._clicks = 0
        self._last_release_ns = None
        return name

    def map(self, sample: MotionSample, profile: Profile) -> MappedState:
        profile = profile.validated()
        identity = (profile.id, profile.revision, profile.mode)
        if self._active_profile is not None and self._active_profile != identity:
            self.reset()
        self._active_profile = identity
        if sample.stage_status != PipelineStageStatus.AVAILABLE:
            self.reset()
            return _neutral(sample, profile)
        if sample.tilt_pitch_deg is None or sample.tilt_roll_deg is None:
            self.reset()
            return _neutral(sample, profile)

        spec = resolve_axis_map(self._axis_map)[profile.mode]
        if profile.mode == "steering":
            wheel_deg = _tilt_deg(sample, str(spec["wheel"]), profile, float(spec["wheel_sign"]))
            throttle_deg = _tilt_deg(
                sample, str(spec["throttle"]), profile, float(spec["throttle_sign"])
            )
            pedal_deg = _tilt_deg(sample, str(spec["brake"]), profile, float(spec["brake_sign"]))
            if wheel_deg is None or throttle_deg is None or pedal_deg is None:
                return _neutral(sample, profile)
            return self._steering(sample, profile, wheel_deg, throttle_deg, pedal_deg)
        if profile.mode == "mouse":
            return self._mouse(sample, profile)
        if profile.mode == "plane":
            return self._plane(sample, profile)
        if profile.mode == "media":
            angle = _tilt_deg(sample, str(spec["volume"]), profile, float(spec["volume_sign"]))
            if angle is None:
                return _neutral(sample, profile)
            return self._media(sample, profile, angle)
        raise ValueError(f"unsupported profile mode {profile.mode!r}")

    def _steering(
        self,
        sample: MotionSample,
        profile: Profile,
        wheel_deg: float,
        throttle_deg: float,
        pedal_deg: float,
    ) -> MappedState:
        """Wheel, throttle, and brake use the configured tilt channels.

        Default map: twist steers. On the vertical mount a forward tip is
        negative pitch, and that side is the gas pedal. A tip back is brake.
        """
        # Wheel, gas, and brake each have their own deadzone and full scale.
        wheel = _shaped_ease(
            wheel_deg, profile.deadzone_deg, profile.full_scale_deg, _WHEEL_EASE
        )
        gas = _shaped_ease(
            throttle_deg,
            profile.throttle_deadzone_deg,
            profile.throttle_full_scale_deg,
            _PEDAL_EASE,
        )
        pedal = _shaped_ease(
            pedal_deg,
            profile.brake_deadzone_deg,
            profile.brake_full_scale_deg,
            _PEDAL_EASE,
        )
        throttle = -gas if gas < 0.0 else 0.0
        brake = pedal if pedal > 0.0 else 0.0
        return self._state(
            sample,
            profile,
            absolute_axes={
                "wheel": wheel,
                "throttle": throttle,
                "brake": brake,
                "wheel_deg": wheel_deg,
                "pitch_deg": pedal_deg,
            },
        )

    def _mouse(self, sample: MotionSample, profile: Profile) -> MappedState:
        """Air mouse: device X tilt → cursor X, device Y tilt → cursor Y.

        Pitch is accelerometer X (left/right). Roll is accelerometer Y (front/back).
        Gyro rate does not move the pointer.
        """
        pulses: list[str] = []
        dt = sample.dt_s if sample.dt_s is not None and 0 < sample.dt_s <= _MOUSE_GAP_S else 0.0
        spec = resolve_axis_map(self._axis_map)["mouse"]
        x_deg = _tilt_deg(sample, str(spec["x"]), profile, profile.mouse_x_sign)
        y_deg = _tilt_deg(sample, str(spec["y"]), profile, profile.mouse_y_sign)
        sx = sy = 0.0
        pointer_x = pointer_y = 0.0
        if x_deg is not None and y_deg is not None and dt > 0.0:
            sx = _shaped(x_deg, profile.deadzone_deg, profile.full_scale_deg)
            sy = _shaped(y_deg, profile.deadzone_deg, profile.full_scale_deg)
            pointer_x = sx * profile.mouse_x_px_per_sec * dt
            pointer_y = sy * profile.mouse_y_px_per_sec * dt
        return self._state(
            sample,
            profile,
            absolute_axes={"lean_x": sx, "lean_y": sy},
            relative_deltas={"pointer_x": pointer_x, "pointer_y": pointer_y},
            pulses=tuple(pulses),
        )

    def _plane(self, sample: MotionSample, profile: Profile) -> MappedState:
        """Joystick knob from held tilt. Gyro rate does not move it.

        Level is center. A tilt stays: 45° is about halfway from center to the
        screen edge when full scale is 90°. The same value is the game stick.
        """
        spec = resolve_axis_map(self._axis_map)["plane"]
        x_deg = _tilt_deg(sample, str(spec["x"]), profile, profile.mouse_x_sign)
        y_deg = _tilt_deg(sample, str(spec["y"]), profile, profile.mouse_y_sign)
        if x_deg is None or y_deg is None:
            stick_x = stick_y = 0.0
        else:
            stick_x = _shaped(x_deg, profile.deadzone_deg, profile.full_scale_deg)
            stick_y = _shaped(y_deg, profile.deadzone_deg, profile.full_scale_deg)
        held = ("trigger",) if sample.button else ()
        return self._state(
            sample,
            profile,
            held_buttons=held,
            absolute_axes={
                "stick_x": stick_x,
                "stick_y": stick_y,
                "pitch_deg": 0.0 if x_deg is None else float(x_deg),
                "roll_deg": 0.0 if y_deg is None else float(y_deg),
            },
        )

    def _media(self, sample: MotionSample, profile: Profile, yaw: float) -> MappedState:
        pulses: list[str] = []
        now = sample.received_monotonic_ns
        self._click_names = dict(_MEDIA_CLICKS)
        self._update_inversion(sample, profile, now, pulses)
        align = sample.gravity_alignment
        falling = align is not None and align <= _INVERT_ENTER
        axes: dict[str, float] = {}
        if self._inverted:
            if not self._system_active:
                self._system_active = True
                self._system_offset = 0.0
                self._prev_yaw = yaw
                self._shake_run = 0
                self._shake_quiet = True
            elif align is not None and align <= -_LEVEL_ALIGN:
                self._update_system_offset(yaw, profile)
            else:
                self._prev_yaw = yaw
            axes = {"system_volume": self._system_offset}
        elif falling:
            self._prev_yaw = yaw
            self._shake_run = 0
            self._shake_quiet = True
        else:
            if self._system_active:
                self._system_active = False
                self._system_offset = 0.0
                self._prev_yaw = yaw
            self._update_clicks(sample, profile, now, pulses)
            if self._media_gestures_enabled:
                self._update_shake(sample, now, pulses, profile)
            if align is None or align >= _LEVEL_ALIGN:
                self._update_volume_endless(yaw, profile)
            else:
                self._prev_yaw = yaw
            axes = {
                "knob": self._volume * 2.0 - 1.0,
                "player_volume": self._volume,
            }
        return self._state(sample, profile, absolute_axes=axes, pulses=tuple(pulses))

    def _update_shake(
        self, sample: MotionSample, now: int | None, pulses: list[str], profile: Profile
    ) -> None:
        """Potrząśnięcie w żyroskopie X/Y. Akcelerometr i skręt Z (głośność) nie przełączają."""
        gyro = sample.gyro_rad_s
        if gyro is None or now is None:
            self._shake_run = 0
            return
        xy_dps = math.degrees(math.hypot(gyro[0], gyro[1]))
        if xy_dps < _SHAKE_XY_DPS:
            self._shake_run = 0
            self._shake_quiet = True
            return
        if not self._shake_quiet:
            return
        lockout_s = float(profile.player_cycle_timeout_s)
        if self._shake_last_ns is not None:
            if (now - self._shake_last_ns) / 1_000_000_000 < lockout_s:
                return
        self._shake_run += 1
        if self._shake_run < _SHAKE_MIN_SAMPLES:
            return
        self._shake_run = 0
        self._shake_quiet = False
        self._shake_last_ns = now
        pulses.append("cycle_player")

    def _update_volume_endless(self, yaw: float, profile: Profile) -> None:
        """Endless knob: twist changes volume; clamp 0–100% with no unwind debt.

        Extra twist past 0% or 100% is discarded, so turning the other way
        reacts immediately. Connect/recenter only seeds the current level.
        """
        if self._prev_yaw is None:
            self._prev_yaw = yaw
            return
        delta = _norm_deg(yaw - self._prev_yaw)
        self._prev_yaw = yaw
        if not self._yaw_step_ok(delta, profile):
            return
        step = max(1.0, float(profile.volume_tilt_deg))
        # Degrees of twist → volume fraction. volume_tilt_deg ≈ degrees for full 0→100.
        self._volume = max(0.0, min(1.0, self._volume + delta / step))

    def _update_system_offset(self, yaw: float, profile: Profile) -> None:
        """Endless twist from flip-in. Cap is upside down, so yaw sign is flipped."""
        if self._prev_yaw is None:
            self._prev_yaw = yaw
            return
        delta = -_norm_deg(yaw - self._prev_yaw)
        self._prev_yaw = yaw
        if not self._yaw_step_ok(delta, profile):
            return
        step = max(1.0, float(profile.volume_tilt_deg))
        self._system_offset += delta / step

    def _yaw_step_ok(self, delta: float, profile: Profile) -> bool:
        if abs(delta) > _YAW_STEP_MAX_DEG:
            return False
        noise = max(_YAW_NOISE_MIN_DEG, profile.deadzone_deg * _YAW_NOISE_FRAC)
        return abs(delta) >= noise

    def _update_clicks(
        self,
        sample: MotionSample,
        profile: Profile,
        now: int | None,
        pulses: list[str],
    ) -> None:
        if now is None or sample.button is None:
            return
        window_ns = int(profile.click_window_s * 1_000_000_000)
        if self._clicks and not self._down and self._last_release_ns is not None:
            if now - self._last_release_ns >= window_ns:
                fallback = next(iter(self._click_names.values()))
                action = self._click_names.get(self._clicks, fallback)
                if action is not None:
                    pulses.append(action)
                self._clicks = 0
                self._last_release_ns = None
        if sample.button and not self._down:
            self._down = True
        elif not sample.button and self._down:
            self._down = False
            self._clicks += 1
            self._last_release_ns = now

    def _update_inversion(
        self,
        sample: MotionSample,
        profile: Profile,
        now: int | None,
        pulses: list[str],
    ) -> None:
        align = sample.gravity_alignment
        if align is None or now is None:
            return
        hold_ns = int(profile.invert_hold_s * 1_000_000_000)
        if align <= _INVERT_ENTER:
            self._upright_since_ns = None
            if self._invert_since_ns is None:
                self._invert_since_ns = now
            elif not self._inverted and now - self._invert_since_ns >= hold_ns:
                self._inverted = True
                self._clicks = 0
                self._down = False
                pulses.append("mute")
        elif align >= _INVERT_EXIT:
            self._invert_since_ns = None
            if not self._inverted:
                self._upright_since_ns = None
                return
            if self._upright_since_ns is None:
                self._upright_since_ns = now
            elif now - self._upright_since_ns >= hold_ns:
                self._inverted = False
                self._upright_since_ns = None
                pulses.append("mute")
        else:
            self._invert_since_ns = None
            self._upright_since_ns = None

    def _binding_outputs(
        self, sample: MotionSample, profile: Profile, axes: dict[str, float],
        legacy_buttons: tuple[str, ...],
    ) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        bindings = self._control_bindings.get(profile.mode, {})
        button = bindings.get("button", "default")
        buttons = list(legacy_buttons if button == "default" else ())
        keys: list[str] = []

        def hold(action: str) -> None:
            if action in KEY_ACTIONS:
                if action not in keys:
                    keys.append(action)
            elif action.startswith("mouse_") and action not in buttons:
                buttons.append(action)

        if sample.button:
            hold(button)
        if profile.mode == "steering":
            x = axes.get("wheel", 0.0)
            forward, backward = axes.get("throttle", 0.0), axes.get("brake", 0.0)
        else:
            prefix = "lean" if profile.mode == "mouse" else "stick"
            x, y = axes.get(f"{prefix}_x", 0.0), axes.get(f"{prefix}_y", 0.0)
            forward, backward = max(0.0, -y), max(0.0, y)
        strengths = {"left": max(0.0, -x), "right": max(0.0, x),
                     "forward": forward, "backward": backward}
        for source, strength in strengths.items():
            active = strength >= 0.20 or (source in self._active_directions and strength > 0.15)
            if active:
                self._active_directions.add(source)
                hold(bindings.get(source, "default"))
            else:
                self._active_directions.discard(source)

        # Held-button overrides suppress *implicit* legacy mouse clicks. Explicit
        # click bindings may coexist with a held binding, including button=off.
        legacy_clicks = _MOUSE_CLICKS if profile.mode == "mouse" and button == "default" else {}
        self._click_names = {}
        for count, source in enumerate(("click", "double_click", "triple_click"), 1):
            action = bindings.get(source, "default")
            self._click_names[count] = legacy_clicks.get(count, legacy_clicks.get(1)) if action == "default" else (
                None if action == "off" else action
            )
        pulses: list[str] = []
        self._update_clicks(sample, profile, sample.received_monotonic_ns, pulses)
        return tuple(buttons), tuple(keys), tuple(pulses)

    def _state(
        self,
        sample: MotionSample,
        profile: Profile,
        *,
        held_buttons: tuple[str, ...] = (),
        absolute_axes: dict[str, float] | None = None,
        relative_deltas: dict[str, float] | None = None,
        pulses: tuple[str, ...] = (),
    ) -> MappedState:
        axes = absolute_axes or {}
        deltas = relative_deltas or {}
        held_keys: tuple[str, ...] = ()
        if profile.mode != "media":
            held_buttons, held_keys, extra_pulses = self._binding_outputs(
                sample, profile, axes, held_buttons
            )
            pulses = (*pulses, *extra_pulses)
        for value in (*axes.values(), *deltas.values()):
            if not math.isfinite(value):
                raise ValueError("mapped value must be finite")
        return MappedState(
            schema_version=SCHEMA_VERSION,
            raw_session_id=sample.raw_session_id,
            raw_connection_epoch=sample.raw_connection_epoch,
            raw_sample_seq=sample.raw_sample_seq,
            profile_id=profile.id,
            profile_revision=profile.revision,
            activation_epoch=0,
            held_buttons=held_buttons,
            held_keys=held_keys,
            absolute_axes=axes,
            relative_deltas=deltas,
            stage_status=PipelineStageStatus.AVAILABLE,
            pulses=pulses,
        )

