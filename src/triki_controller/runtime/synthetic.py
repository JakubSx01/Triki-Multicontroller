"""Synthetic IMU counts at the reference-hypothesis scale, for offline tests.

Counts use 2048 LSB per g. This is not a recording of the physical CAP001.
Poses are authored in the control frame; pass them through ``unmap_counts``
when a test feeds ``EmulatorRuntime`` with a non-identity mount.
"""

from __future__ import annotations

import math

from triki_controller.core.models import SCHEMA_VERSION, QualityFlags, RawSample

_SCALE = 2048.0


def counts_from_g(ax: float, ay: float, az: float) -> tuple[int, int, int]:
    return (
        int(round(ax * _SCALE)),
        int(round(ay * _SCALE)),
        int(round(az * _SCALE)),
    )


def pose_roll_deg(degrees: float) -> tuple[int, int, int]:
    radians = math.radians(degrees)
    return counts_from_g(0.0, math.sin(radians), -math.cos(radians))


def pose_pitch_deg(degrees: float) -> tuple[int, int, int]:
    radians = math.radians(degrees)
    return counts_from_g(math.sin(radians), 0.0, -math.cos(radians))


def pose_level() -> tuple[int, int, int]:
    return counts_from_g(0.0, 0.0, -1.0)


def pose_face_down() -> tuple[int, int, int]:
    return counts_from_g(0.0, 0.0, 1.0)


def make_raw(
    *,
    accel: tuple[int, int, int],
    seq: int,
    t_ns: int,
    button: bool = False,
    gyro: tuple[int, int, int] = (0, 0, 0),
    session_id: str = "synthetic",
) -> RawSample:
    return RawSample(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        connection_epoch=1,
        sample_seq=seq,
        received_monotonic_ns=t_ns,
        source_notification_seqs=(seq,),
        protocol_revision="reference-hypothesis",
        raw_frame=b"",
        accel_counts=accel,
        gyro_counts=gyro,
        button=button,
        device_tick=None,
        battery_percent=None,
        rssi_dbm=None,
        quality_flags=QualityFlags(
            synthetic=True,
            not_measured=True,
            notes=("scripted pose, not a CAP001 capture",),
        ),
    )


# Gyro Z counts at reference-hypothesis 131 LSB/(deg/s). Positive control-frame Z
# rate decreases integrated yaw in TiltMotionProcessor; negate to twist "right".
_GYRO_COUNTS_PER_DPS = 131.0


def gyro_yaw_twist_counts(yaw_rate_deg_s: float) -> tuple[int, int, int]:
    """Control-frame gyro counts that integrate to +yaw_rate_deg_s."""
    gz = int(round(-yaw_rate_deg_s * _GYRO_COUNTS_PER_DPS))
    return (0, 0, gz)


def gyro_pitch_rate_counts(pitch_rate_deg_s: float) -> tuple[int, int, int]:
    """Control-frame gyro counts for +pitch_rate_deg_s (nose up)."""
    gy = int(round(pitch_rate_deg_s * _GYRO_COUNTS_PER_DPS))
    return (0, gy, 0)
