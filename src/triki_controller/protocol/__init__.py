"""Protocol parsing — synthetic-v0 plus provisional CAP001 reference-hypothesis."""

from __future__ import annotations

from triki_controller.protocol.cap001_hypothesis import (
    REFERENCE_HYPOTHESIS_REVISION,
    Cap001HypothesisFrameParser,
    encode_cap001_hypothesis_frame,
)
from triki_controller.protocol.parser import (
    SYNTHETIC_REVISION,
    DisabledFrameParser,
    FrameParser,
    ProtocolDescriptor,
    SyntheticFrameParser,
    encode_synthetic_frame,
)

__all__ = [
    "REFERENCE_HYPOTHESIS_REVISION",
    "SYNTHETIC_REVISION",
    "Cap001HypothesisFrameParser",
    "DisabledFrameParser",
    "FrameParser",
    "ProtocolDescriptor",
    "SyntheticFrameParser",
    "encode_cap001_hypothesis_frame",
    "encode_synthetic_frame",
]
