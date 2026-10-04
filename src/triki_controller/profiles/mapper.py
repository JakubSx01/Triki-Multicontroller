"""Profile mapper stub — PROFILE MAPPING stage explicitly unavailable."""

from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    MotionSample,
    PipelineStageStatus,
)


@runtime_checkable
class ProfileMapper(Protocol):
    def map(self, sample: MotionSample, profile: Mapping[str, object]) -> MappedState:
        ...

    def reset(self) -> None:
        ...


class UnavailableProfileMapper:
    def map(self, sample: MotionSample, profile: Mapping[str, object]) -> MappedState:
        return MappedState(
            schema_version=SCHEMA_VERSION,
            raw_session_id=sample.raw_session_id,
            raw_connection_epoch=sample.raw_connection_epoch,
            raw_sample_seq=sample.raw_sample_seq,
            profile_id=None,
            profile_revision=None,
            activation_epoch=0,
            held_buttons=(),
            held_keys=(),
            absolute_axes={},
            relative_deltas={},
            stage_status=PipelineStageStatus.UNAVAILABLE,
        )

    def reset(self) -> None:
        return None
