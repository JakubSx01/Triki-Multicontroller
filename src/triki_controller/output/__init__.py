"""Output backends."""

from triki_controller.output.base import OutputBackend
from triki_controller.output.fake import FakeOutput
from triki_controller.output.mpris_volume import MprisPlayerStatus, MprisPlayerVolume
from triki_controller.output.trace import TraceOutput

__all__ = [
    "FakeOutput",
    "MprisPlayerStatus",
    "MprisPlayerVolume",
    "OutputBackend",
    "TraceOutput",
]
