"""Immutable diagnostic records (schema_version=1).

Unknown measurements are None (null), never invented zeros.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence

SCHEMA_VERSION = 1

Tuple3 = tuple[int, int, int]
FloatTuple3 = tuple[float, float, float]
Quaternion = tuple[float, float, float, float]


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    STREAMING = "streaming"
    ERROR = "error"


class PipelineStageStatus(str, Enum):
    """Visibility for RAW → FILTERED → PROFILE MAPPING → FINAL OUTPUT."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DISABLED = "disabled"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class QualityFlags:
    incomplete_frame: bool = False
    resync: bool = False
    discarded_bytes: int = 0
    synthetic: bool = False
    not_measured: bool = False
    notes: tuple[str, ...] = ()

    def to_mapping(self) -> dict[str, object]:
        return {
            "incomplete_frame": self.incomplete_frame,
            "resync": self.resync,
            "discarded_bytes": self.discarded_bytes,
            "synthetic": self.synthetic,
            "not_measured": self.not_measured,
            "notes": list(self.notes),
        }


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    schema_version: int
    session_id: str
    connection_epoch: int
    event_seq: int
    host_monotonic_ns: int
    state: ConnectionState
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class Notification:
    schema_version: int
    session_id: str
    connection_epoch: int
    notification_seq: int
    received_monotonic_ns: int
    characteristic_uuid: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class RawSample:
    schema_version: int
    session_id: str
    connection_epoch: int
    sample_seq: int
    received_monotonic_ns: int
    source_notification_seqs: tuple[int, ...]
    protocol_revision: str
    raw_frame: bytes
    accel_counts: Tuple3
    gyro_counts: Tuple3
    button: bool | None
    device_tick: int | None
    battery_percent: float | None
    rssi_dbm: int | None
    quality_flags: QualityFlags = field(default_factory=QualityFlags)


@dataclass(frozen=True, slots=True)
class ParseDiagnostic:
    schema_version: int
    session_id: str
    connection_epoch: int
    received_monotonic_ns: int
    source_notification_seqs: tuple[int, ...]
    kind: str
    detail: str
    discarded_bytes: int = 0


@dataclass(frozen=True, slots=True)
class MotionSample:
    """FILTERED stage — unavailable in slice 1 until measured protocol exists."""

    schema_version: int
    raw_session_id: str
    raw_connection_epoch: int
    raw_sample_seq: int
    dt_s: float | None
    accel_m_s2: FloatTuple3 | None
    gyro_rad_s: FloatTuple3 | None
    relative_orientation: Quaternion | None
    calibration_revision: str | None
    quality_flags: QualityFlags
    stage_status: PipelineStageStatus = PipelineStageStatus.UNAVAILABLE
    # Preserved from RAW. None means the frame did not carry a button bit.
    button: bool | None = None
    received_monotonic_ns: int | None = None
    # Degrees, relative to the last recenter. Yaw is integrated and drifts;
    # it is not an absolute heading.
    tilt_pitch_deg: float | None = None
    tilt_roll_deg: float | None = None
    tilt_yaw_deg: float | None = None
    # Dot product of the current gravity unit vector and the recenter reference.
    # +1 same pose, -1 flipped. None until a gravity reference exists.
    gravity_alignment: float | None = None


@dataclass(frozen=True, slots=True)
class MappedState:
    """PROFILE MAPPING stage — unavailable in slice 1."""

    schema_version: int
    raw_session_id: str
    raw_connection_epoch: int
    raw_sample_seq: int
    profile_id: str | None
    profile_revision: str | None
    activation_epoch: int
    held_buttons: tuple[str, ...]
    held_keys: tuple[str, ...]
    absolute_axes: Mapping[str, float]
    relative_deltas: Mapping[str, float]
    stage_status: PipelineStageStatus = PipelineStageStatus.UNAVAILABLE
    # One-shot logical controls for this sample (volume, mute, track). Not evdev codes.
    pulses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class OutputReceipt:
    """FINAL OUTPUT stage — fake dry-run only in slice 1."""

    schema_version: int
    raw_session_id: str
    raw_connection_epoch: int
    raw_sample_seq: int
    activation_epoch: int
    backend: str
    emitted_monotonic_ns: int
    applied: bool
    dry_run: bool
    neutralization_reason: str | None
    detail: str | None = None
    stage_status: PipelineStageStatus = PipelineStageStatus.DISABLED


@dataclass(frozen=True, slots=True)
class StageSnapshot:
    """Visible pipeline status for diagnosis."""

    raw: PipelineStageStatus
    filtered: PipelineStageStatus
    profile_mapping: PipelineStageStatus
    final_output: PipelineStageStatus

    def as_dict(self) -> dict[str, str]:
        return {
            "RAW": self.raw.value,
            "FILTERED": self.filtered.value,
            "PROFILE_MAPPING": self.profile_mapping.value,
            "FINAL_OUTPUT": self.final_output.value,
        }


SLICE1_PIPELINE = StageSnapshot(
    raw=PipelineStageStatus.AVAILABLE,
    filtered=PipelineStageStatus.UNAVAILABLE,
    profile_mapping=PipelineStageStatus.UNAVAILABLE,
    final_output=PipelineStageStatus.DISABLED,
)


def require_tuple3_int(values: Sequence[int], name: str) -> Tuple3:
    if len(values) != 3:
        raise ValueError(f"{name} must have exactly 3 elements")
    a, b, c = (int(values[0]), int(values[1]), int(values[2]))
    return (a, b, c)
