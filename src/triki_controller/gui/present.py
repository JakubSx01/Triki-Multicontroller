"""Pure formatters for the desktop UI. Missing measurements stay unavailable."""

from __future__ import annotations

import math

from triki_controller.core.models import MappedState, MotionSample, RawSample
from triki_controller.transport.ble import humanize_ble_error

CONNECTION_LABELS = {
    "disconnected": "Rozłączono",
    "scanning": "Skanowanie BLE",
    "connecting": "Łączenie",
    "streaming": "Połączono",
    "error": "Błąd połączenia",
}

OUTPUT_LABELS = {
    "off": "Wyłączone",
    "dry-run": "Próbne (bez systemu)",
    "live": "Na żywo",
}


def format_measure(value: object, digits: int) -> str:
    """Signed number, or 'niedostępne' when the channel was not measured."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return "niedostępne"
    if not math.isfinite(value):
        return "niedostępne"
    if digits <= 0:
        return f"{value:+.0f}"
    return f"{value:+.{digits}f}"


def friendly_connection_detail(state: str, reason: str | None) -> str:
    """Operator-facing connection copy. Never show Bleak exception repr."""
    blob = (reason or "").strip()
    lower = blob.lower()
    if state == "scanning":
        return "Naciśnij raz przycisk na nakładce Triki, żeby się ogłosiła (okno skanowania ~30 s)."
    if state == "connecting":
        return blob or "Łączenie z nakładką…"
    if state == "streaming":
        return blob or "Połączono. Strumień jest aktywny."
    if state == "disconnected":
        if "przycisk" in lower or "skan" in lower:
            return blob
        return blob or "Rozłączono."
    if "bleak" in lower or "unlikely" in lower or "gatt protocol" in lower:
        return humanize_ble_error(RuntimeError(blob))
    if blob.startswith("ble error:") or blob.startswith("błąd ble:"):
        return humanize_ble_error(RuntimeError(blob))
    return blob


def connection_label(state: str) -> str:
    return CONNECTION_LABELS.get(state, "Stan nieznany")


def output_label(mode: str) -> str:
    return OUTPUT_LABELS.get(mode, mode)


def button_label(button: bool | None) -> str:
    if button is None:
        return "Przycisk: niedostępny"
    if button:
        return "Przycisk: wciśnięty"
    return "Przycisk: zwolniony"


def battery_label(percent: float | None) -> str:
    if percent is None:
        return "Bateria: niedostępna"
    return f"Bateria: {format_measure(percent, 0)}%"


def rssi_label(rssi_dbm: int | None) -> str:
    if rssi_dbm is None:
        return "RSSI: niedostępne"
    return f"RSSI: {format_measure(rssi_dbm, 0)} dBm"


def sensor_channels(snap: SessionSnapshot) -> dict[str, object]:
    """Raw and filtered channels. Absent fields stay None, never a fake zero."""
    raw: RawSample | None = snap.raw
    motion: MotionSample | None = snap.motion
    gyro = None if motion is None else motion.gyro_rad_s
    gyro_dps = None if gyro is None else tuple(math.degrees(axis) for axis in gyro)
    return {
        "accel_counts": None if raw is None else tuple(raw.accel_counts),
        "gyro_counts": None if raw is None else tuple(raw.gyro_counts),
        "accel_m_s2": None if motion is None else motion.accel_m_s2,
        "gyro_rad_s": gyro,
        "gyro_dps": gyro_dps,
        "tilt_pitch_deg": None if motion is None else motion.tilt_pitch_deg,
        "tilt_roll_deg": None if motion is None else motion.tilt_roll_deg,
        "tilt_yaw_deg": None if motion is None else motion.tilt_yaw_deg,
        "button": None if raw is None else raw.button,
        "battery_percent": snap.battery_percent,
        "rssi_dbm": snap.rssi_dbm,
        "device_tick": None if raw is None else raw.device_tick,
        "gravity_alignment": None if motion is None else motion.gravity_alignment,
        "dt_s": None if motion is None else motion.dt_s,
        "sample_seq": None if raw is None else raw.sample_seq,
        "protocol_revision": None if raw is None else raw.protocol_revision,
        "frame_bytes": None if raw is None else len(raw.raw_frame),
        "relative_orientation": None if motion is None else motion.relative_orientation,
    }


def format_mapped(mapped: MappedState | None) -> str:
    if mapped is None:
        return "Brak zmapowanych osi."
    parts: list[str] = []
    for key, value in mapped.absolute_axes.items():
        parts.append(f"{key} {format_measure(value, 3)}")
    for key, value in mapped.relative_deltas.items():
        parts.append(f"{key} {format_measure(value, 3)}")
    if mapped.pulses:
        parts.append("impulsy: " + ", ".join(mapped.pulses))
    held = list(mapped.held_buttons) + list(mapped.held_keys)
    if held:
        parts.append("trzymane: " + ", ".join(held))
    if not parts:
        return "Brak zmapowanych osi."
    return " · ".join(parts)


def steering_preview(mapped: MappedState | None) -> dict[str, float | None]:
    """PROFILE MAPPING values for the config live preview (not raw IMU)."""
    if mapped is None:
        return {"wheel": None, "throttle": None, "brake": None}
    axes = mapped.absolute_axes
    return {
        "wheel": _finite_or_none(axes.get("wheel")),
        "throttle": _finite_or_none(axes.get("throttle")),
        "brake": _finite_or_none(axes.get("brake")),
    }


def mouse_preview(
    mapped: MappedState | None, pointer_px_per_s: tuple[float, float] | None
) -> dict[str, object]:
    if mapped is None:
        return {"dx": None, "dy": None, "pulses": ()}
    dx = dy = None
    if pointer_px_per_s is not None:
        dx, dy = pointer_px_per_s
    return {
        "dx": dx,
        "dy": dy,
        "pulses": tuple(mapped.pulses),
    }


def media_preview(mapped: MappedState | None) -> dict[str, object]:
    if mapped is None:
        return {"volume": None, "pulses": ()}
    return {
        "volume": _finite_or_none(mapped.absolute_axes.get("player_volume")),
        "system": "system_volume" in mapped.absolute_axes,
        "pulses": tuple(mapped.pulses),
    }


def _finite_or_none(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def map_profile_preview(
    motion: MotionSample | None,
    *,
    profile_name: str,
    settings: object,
) -> MappedState | None:
    """Map one motion sample for a profile without touching the live session mapper."""
    if motion is None:
        return None
    from triki_controller.gui.settings import GuiSettings, THRESHOLD_FIELDS
    from triki_controller.profiles.builtin import profile_by_name, with_overrides
    from triki_controller.profiles.devices import DeviceProfileMapper

    if not isinstance(settings, GuiSettings):
        return None
    base = profile_by_name(
        profile_name,
        invert_pitch=settings.invert_pitch,
        invert_roll=settings.invert_roll,
    )
    overrides = {
        key: float(value)
        for key, value in settings.thresholds.get(profile_name, {}).items()
        if key in THRESHOLD_FIELDS
    }
    profile = with_overrides(base, **overrides) if overrides else base
    mapper = DeviceProfileMapper()
    mapper.set_axis_map(settings.axis_map)
    return mapper.map(motion, profile)
