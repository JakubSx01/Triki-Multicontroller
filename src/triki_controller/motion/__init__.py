"""Motion processing.

`UnavailableMotionProcessor` stays the monitor/record default.
`TiltMotionProcessor` is the emulator FILTERED stage (reference-hypothesis scales).
Mounting orientation remaps axes before tilt; see `motion.orientation`.
"""

from triki_controller.motion.orientation import (
    DEFAULT_ORIENTATION,
    ORIENTATION_IDS,
    MountingOrientation,
    get_orientation,
    orientation_choices,
    orientation_labels_pl,
    parse_orientation,
    remap_counts,
    remap_vector,
)
from triki_controller.motion.processor import MotionProcessor, UnavailableMotionProcessor
from triki_controller.motion.tilt import TiltMotionProcessor

__all__ = [
    "DEFAULT_ORIENTATION",
    "ORIENTATION_IDS",
    "MotionProcessor",
    "MountingOrientation",
    "TiltMotionProcessor",
    "UnavailableMotionProcessor",
    "get_orientation",
    "orientation_choices",
    "orientation_labels_pl",
    "parse_orientation",
    "remap_counts",
    "remap_vector",
]