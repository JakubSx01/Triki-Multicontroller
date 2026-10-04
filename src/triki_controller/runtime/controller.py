"""Runtime orchestration for slice 1: RAW available; later stages unavailable."""

from __future__ import annotations

from dataclasses import dataclass, field

from triki_controller.core.models import (
    SLICE1_PIPELINE,
    ConnectionEvent,
    ConnectionState,
    Notification,
    ParseDiagnostic,
    RawSample,
    StageSnapshot,
)
from triki_controller.motion.processor import UnavailableMotionProcessor
from triki_controller.output.fake import FakeOutput
from triki_controller.profiles.mapper import UnavailableProfileMapper
from triki_controller.protocol.parser import FrameParser, SyntheticFrameParser


@dataclass
class RuntimeStats:
    samples: int = 0
    parse_diagnostics: int = 0
    reconnects: int = 0
    connection_events: int = 0
    last_state: ConnectionState | None = None


@dataclass
class RuntimeController:
    """Preserves RAW → FILTERED → PROFILE MAPPING → FINAL OUTPUT boundaries."""

    parser: FrameParser = field(default_factory=SyntheticFrameParser)
    motion: UnavailableMotionProcessor = field(default_factory=UnavailableMotionProcessor)
    mapper: UnavailableProfileMapper = field(default_factory=UnavailableProfileMapper)
    output: FakeOutput = field(default_factory=FakeOutput)
    stats: RuntimeStats = field(default_factory=RuntimeStats)
    _epoch: int | None = None
    _active: bool = False

    def pipeline_status(self) -> StageSnapshot:
        return SLICE1_PIPELINE

    def handle_connection(self, event: ConnectionEvent) -> None:
        self.stats.connection_events += 1
        prev = self.stats.last_state
        self.stats.last_state = event.state
        if event.state == ConnectionState.STREAMING and (
            prev in (ConnectionState.DISCONNECTED, ConnectionState.CONNECTING, ConnectionState.ERROR)
            or prev is None
        ):
            if self._epoch is not None and event.connection_epoch != self._epoch:
                self.stats.reconnects += 1
            self.parser.reset(event.connection_epoch)
            self._epoch = event.connection_epoch
        if event.state in (ConnectionState.DISCONNECTED, ConnectionState.ERROR):
            self.deactivate(reason=event.reason or event.state.value)

    def handle_notification(self, notification: Notification) -> list[RawSample | ParseDiagnostic]:
        results = self.parser.feed(notification)
        samples: list[RawSample] = []
        for item in results:
            if isinstance(item, RawSample):
                self.stats.samples += 1
                samples.append(item)
                # Later stages remain unavailable — call stubs for visibility only.
                motion = self.motion.process(item)
                assert motion.stage_status.value == "unavailable"
                mapped = self.mapper.map(motion, {})
                assert mapped.stage_status.value == "unavailable"
            else:
                self.stats.parse_diagnostics += 1
        return results

    def activate(self) -> None:
        """Explicit activation — output stays dry-run disabled in slice 1."""
        self.output.open({"claim_uinput": False, "dry_run": True})
        self._active = True

    def deactivate(self, reason: str) -> None:
        if self._active or self.output.opened:
            self.output.neutralize(reason)
        self._active = False
        self.mapper.reset()
        self.motion.reset_time()
