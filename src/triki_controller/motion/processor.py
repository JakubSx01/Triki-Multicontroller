"""Motion processor stub — FILTERED stage explicitly unavailable."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MotionSample,
    PipelineStageStatus,
    QualityFlags,
    RawSample,
)


@runtime_checkable
class MotionProcessor(Protocol):
    def process(self, sample: RawSample) -> MotionSample:
        ...

    def reset_time(self) -> None:
        ...


class UnavailableMotionProcessor:
    """Slice 1: no unit conversion without measured ProtocolDescriptor."""

    def process(self, sample: RawSample) -> MotionSample:
        return MotionSample(
            schema_version=SCHEMA_VERSION,
            raw_session_id=sample.session_id,
            raw_connection_epoch=sample.connection_epoch,
            raw_sample_seq=sample.sample_seq,
            dt_s=None,
            accel_m_s2=None,
            gyro_rad_s=None,
            relative_orientation=None,
            calibration_revision=None,
            quality_flags=QualityFlags(
                synthetic=sample.quality_flags.synthetic,
                notes=("FILTERED unavailable: no measured scaling",),
            ),
            stage_status=PipelineStageStatus.UNAVAILABLE,
        )

    def calibrate(self, stationary_window: list[RawSample]) -> dict[str, object]:
        raise RuntimeError("Calibration unavailable until measured protocol descriptor exists")

    def recenter(self) -> None:
        raise RuntimeError("Recenter unavailable until motion stage is enabled")

    def reset_time(self) -> None:
        return None
