"""Gravity-aided pitch/roll from RAW counts.

Scales match the TrikiScope reference hypothesis (LSM6DSL ±250 dps / ±16 g:
131 LSB per deg/s, 2048 LSB per g). They are not a HOM-27 signed-off
descriptor. Pitch and roll are corrected by the accelerometer, so they stay
tied to gravity. Yaw is gyro integration only and drifts; nothing here treats
it as a compass heading.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MotionSample,
    PipelineStageStatus,
    QualityFlags,
    RawSample,
)
from triki_controller.motion.orientation import (
    DEFAULT_ORIENTATION,
    MountingOrientation,
    get_orientation,
    parse_orientation,
    remap_vector,
)

ACCEL_COUNTS_PER_G = 2048.0
GYRO_COUNTS_PER_DPS = 131.0
G_M_S2 = 9.80665
_RAD2DEG = 180.0 / math.pi
_DEG2RAD = math.pi / 180.0

# Accel magnitude outside this band is not gravity (shake, free-fall).
_ACCEL_G_MIN = 0.65
_ACCEL_G_MAX = 1.35
# Gaps longer than this must not be integrated.
_MAX_INTEGRATION_DT_S = 0.25


def _norm_deg(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def _blend_deg(current: float, target: float, hold: float) -> float:
    """`hold` keeps the current angle; the rest moves toward the target on the short arc."""
    delta = _norm_deg(target - current)
    return _norm_deg(current + delta * (1.0 - hold))


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _quat_mul(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _quat_axis(ax: float, ay: float, az: float, degrees: float) -> tuple[float, float, float, float]:
    length = math.sqrt(ax * ax + ay * ay + az * az)
    if length == 0.0:
        return (0.0, 0.0, 0.0, 1.0)
    half = degrees * _DEG2RAD * 0.5
    scale = math.sin(half) / length
    return (ax * scale, ay * scale, az * scale, math.cos(half))


def euler_to_quaternion(
    pitch_deg: float, roll_deg: float, yaw_deg: float
) -> tuple[float, float, float, float]:
    """(x, y, z, w). Yaw, then pitch, then roll. Diagnostic only."""
    qz = _quat_axis(0.0, 0.0, 1.0, yaw_deg)
    qy = _quat_axis(0.0, 1.0, 0.0, pitch_deg)
    qx = _quat_axis(1.0, 0.0, 0.0, roll_deg)
    return _quat_mul(_quat_mul(qz, qy), qx)


def accel_tilt_deg(ax_g: float, ay_g: float, az_g: float) -> tuple[float, float] | None:
    """Pitch/roll in degrees from a gravity vector, or None if it is not 1 g.

    Pitch is atan2(ax, hypot(ay, az)). Roll is atan2(ay, -az). Same axis
    reading as the TrikiScope complementary tilt path; not a measured
    CAP001 axis sign-off.
    """
    mag = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)
    if mag < _ACCEL_G_MIN or mag > _ACCEL_G_MAX:
        return None
    horizontal = math.sqrt(ay_g * ay_g + az_g * az_g)
    pitch = math.atan2(ax_g, horizontal) * _RAD2DEG
    roll = math.atan2(ay_g, -az_g) * _RAD2DEG
    return pitch, roll


@dataclass
class CalibrationResult:
    accepted: bool
    revision: str | None
    gyro_bias_dps: tuple[float, float, float] | None
    detail: str


class TiltMotionProcessor:
    """FILTERED stage: counts → m/s², rad/s, and gravity-relative tilt."""

    def __init__(
        self,
        *,
        accel_counts_per_g: float = ACCEL_COUNTS_PER_G,
        gyro_counts_per_dps: float = GYRO_COUNTS_PER_DPS,
        complementary_alpha: float = 0.8,
        orientation: str = DEFAULT_ORIENTATION,
    ) -> None:
        if accel_counts_per_g <= 0 or gyro_counts_per_dps <= 0:
            raise ValueError("sensor scales must be positive")
        self._accel_scale = accel_counts_per_g
        self._gyro_scale = gyro_counts_per_dps
        self._alpha = _clamp(complementary_alpha, 0.0, 1.0)
        self._orientation = get_orientation(orientation)
        self._pitch = 0.0
        self._roll = 0.0
        self._yaw = 0.0
        self._pitch_off = 0.0
        self._roll_off = 0.0
        self._yaw_off = 0.0
        self._bias = (0.0, 0.0, 0.0)
        self._bias_revision: str | None = None
        self._origin_revision: str | None = None
        self._origin_n = 0
        self._last_ns: int | None = None
        self._have_pose = False
        self._last_unit: tuple[float, float, float] | None = None
        self._ref_unit: tuple[float, float, float] | None = None

    @property
    def orientation(self) -> MountingOrientation:
        return self._orientation

    def set_orientation(self, orientation: str) -> None:
        """Change mounting frame. Resets temporal integration; caller should re-arm."""
        parsed = parse_orientation(orientation)
        if parsed == self._orientation.id:
            return
        self._orientation = get_orientation(parsed)
        self.reset_pose()

    def reset_time(self) -> None:
        self._last_ns = None

    def reset_pose(self) -> None:
        """Drop integrated pose after a mounting change or long gap. Bias is kept."""
        self._last_ns = None
        self._have_pose = False
        self._pitch = 0.0
        self._roll = 0.0
        self._yaw = 0.0
        self._pitch_off = 0.0
        self._roll_off = 0.0
        self._yaw_off = 0.0
        self._last_unit = None
        self._ref_unit = None
        self._origin_revision = None
        self._origin_n = 0

    def recenter(self) -> None:
        """Move the control origin to the current pose. Does not change gyro bias."""
        self._pitch_off = self._pitch
        self._roll_off = self._roll
        self._yaw_off = self._yaw
        self._origin_n += 1
        self._origin_revision = f"origin:{self._origin_n}"
        if self._last_unit is not None:
            self._ref_unit = self._last_unit

    def calibrate(self, stationary_window: list[RawSample]) -> CalibrationResult:
        """Estimate gyro bias. Rejects a window that is not steady; keeps the old bias."""
        if len(stationary_window) < 5:
            return CalibrationResult(False, self._revision(), None, "need at least 5 samples")
        gyros: list[tuple[float, float, float]] = []
        for sample in stationary_window:
            ax, ay, az = (
                c / self._accel_scale for c in remap_vector(sample.accel_counts, self._orientation)
            )
            mag = math.sqrt(ax * ax + ay * ay + az * az)
            if mag < 0.85 or mag > 1.15:
                return CalibrationResult(
                    False, self._revision(), None, "accelerometer is not near 1 g"
                )
            gx, gy, gz = (
                c / self._gyro_scale for c in remap_vector(sample.gyro_counts, self._orientation)
            )
            gyros.append((gx, gy, gz))
        means = tuple(sum(axis[i] for axis in gyros) / len(gyros) for i in range(3))
        variances = tuple(
            sum((axis[i] - means[i]) ** 2 for axis in gyros) / len(gyros) for i in range(3)
        )
        if max(variances) > 25.0:
            return CalibrationResult(
                False,
                self._revision(),
                None,
                "gyro variance too high; previous bias kept",
            )
        self._bias = (float(means[0]), float(means[1]), float(means[2]))
        self._bias_revision = f"bias:{means[0]:.2f},{means[1]:.2f},{means[2]:.2f}"
        return CalibrationResult(True, self._revision(), self._bias, "gyro bias updated")

    def process(self, sample: RawSample) -> MotionSample:
        ax_g, ay_g, az_g = (
            c / self._accel_scale for c in remap_vector(sample.accel_counts, self._orientation)
        )
        gx_raw, gy_raw, gz_raw = (
            c / self._gyro_scale for c in remap_vector(sample.gyro_counts, self._orientation)
        )
        gx_dps = gx_raw - self._bias[0]
        gy_dps = gy_raw - self._bias[1]
        gz_dps = gz_raw - self._bias[2]

        notes = [
            "reference-hypothesis scales 2048 LSB/g and 131 LSB/(deg/s)",
            "pitch/roll gravity-aided; yaw is relative and drifts",
            f"mounting orientation={self._orientation.id} (not HOM-27 measured)",
        ]
        dt_s: float | None = None
        integrate = False
        if self._last_ns is not None:
            dt_s = (sample.received_monotonic_ns - self._last_ns) / 1_000_000_000
            if dt_s <= 0:
                notes.append("integration reset: non-positive dt")
                dt_s = None
            elif dt_s > _MAX_INTEGRATION_DT_S:
                notes.append("integration reset: gap")
                dt_s = None
            else:
                integrate = True
        self._last_ns = sample.received_monotonic_ns

        if integrate:
            pred_pitch = self._pitch + gy_dps * dt_s  # type: ignore[operator]
            pred_roll = self._roll - gx_dps * dt_s  # type: ignore[operator]
            pred_yaw = self._yaw - gz_dps * dt_s  # type: ignore[operator]
        else:
            pred_pitch, pred_roll, pred_yaw = self._pitch, self._roll, self._yaw

        tilt = accel_tilt_deg(ax_g, ay_g, az_g)
        if tilt is not None:
            jump = self._have_pose and (
                abs(_norm_deg(tilt[0] - self._pitch)) > 45.0
                or abs(_norm_deg(tilt[1] - self._roll)) > 45.0
            )
            if not self._have_pose or jump:
                # Snap across a flip so the filter does not slew through every angle.
                self._pitch, self._roll = tilt
                self._yaw = pred_yaw
                self._have_pose = True
                if jump:
                    notes.append("tilt snap: gravity jumped")
            else:
                a = self._alpha
                self._pitch = _blend_deg(pred_pitch, tilt[0], a)
                self._roll = _blend_deg(pred_roll, tilt[1], a)
                self._yaw = _norm_deg(pred_yaw)
            mag = math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g)
            self._last_unit = (ax_g / mag, ay_g / mag, az_g / mag)
        elif self._have_pose and integrate:
            self._pitch, self._roll, self._yaw = pred_pitch, pred_roll, pred_yaw
            notes.append("accel rejected; coasting on gyro")

        self._pitch = _norm_deg(self._pitch)
        self._roll = _norm_deg(self._roll)
        self._yaw = _norm_deg(self._yaw)

        rel_pitch = _norm_deg(self._pitch - self._pitch_off) if self._have_pose else None
        rel_roll = _norm_deg(self._roll - self._roll_off) if self._have_pose else None
        rel_yaw = _norm_deg(self._yaw - self._yaw_off) if self._have_pose else None
        orientation = None
        if rel_pitch is not None and rel_roll is not None and rel_yaw is not None:
            orientation = euler_to_quaternion(rel_pitch, rel_roll, rel_yaw)

        alignment = None
        if self._last_unit is not None and self._ref_unit is not None and tilt is not None:
            alignment = (
                self._last_unit[0] * self._ref_unit[0]
                + self._last_unit[1] * self._ref_unit[1]
                + self._last_unit[2] * self._ref_unit[2]
            )

        return MotionSample(
            schema_version=SCHEMA_VERSION,
            raw_session_id=sample.session_id,
            raw_connection_epoch=sample.connection_epoch,
            raw_sample_seq=sample.sample_seq,
            dt_s=dt_s,
            accel_m_s2=(ax_g * G_M_S2, ay_g * G_M_S2, az_g * G_M_S2),
            gyro_rad_s=(gx_dps * _DEG2RAD, gy_dps * _DEG2RAD, gz_dps * _DEG2RAD),
            relative_orientation=orientation,
            calibration_revision=self._revision(),
            quality_flags=QualityFlags(
                synthetic=sample.quality_flags.synthetic,
                not_measured=True,
                notes=tuple(notes),
            ),
            stage_status=PipelineStageStatus.AVAILABLE,
            button=sample.button,
            received_monotonic_ns=sample.received_monotonic_ns,
            tilt_pitch_deg=rel_pitch,
            tilt_roll_deg=rel_roll,
            tilt_yaw_deg=rel_yaw,
            gravity_alignment=alignment,
        )

    def _revision(self) -> str | None:
        parts = [p for p in (self._bias_revision, self._origin_revision) if p]
        return "+".join(parts) if parts else None
