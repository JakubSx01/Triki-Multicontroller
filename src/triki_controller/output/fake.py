"""Fake output sink — dry-run labeled; never claims uinput/mouse/joystick."""

from __future__ import annotations

import time

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    OutputReceipt,
    PipelineStageStatus,
)


class FakeOutput:
    """Records neutralize/apply calls for tests. Dry-run only."""

    BACKEND_NAME = "fake-dry-run"

    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.receipts: list[OutputReceipt] = []
        self._activation_epoch = 0
        self._held: set[str] = set()

    def open(self, capabilities: dict[str, object]) -> None:
        if capabilities.get("claim_uinput"):
            raise RuntimeError("FakeOutput refuses uinput claims")
        self.opened = True
        self.closed = False

    def apply(self, state: MappedState) -> OutputReceipt:
        if not self.opened or self.closed:
            raise RuntimeError("FakeOutput is not open")
        self._held = set(state.held_buttons) | set(state.held_keys)
        receipt = OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id=state.raw_session_id,
            raw_connection_epoch=state.raw_connection_epoch,
            raw_sample_seq=state.raw_sample_seq,
            activation_epoch=state.activation_epoch,
            backend=self.BACKEND_NAME,
            emitted_monotonic_ns=time.monotonic_ns(),
            applied=False,
            dry_run=True,
            neutralization_reason=None,
            detail="dry-run apply; no Linux input emitted",
            stage_status=PipelineStageStatus.DISABLED,
        )
        self.receipts.append(receipt)
        return receipt

    def neutralize(self, reason: str) -> OutputReceipt:
        self._activation_epoch += 1
        self._held.clear()
        receipt = OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id="",
            raw_connection_epoch=0,
            raw_sample_seq=0,
            activation_epoch=self._activation_epoch,
            backend=self.BACKEND_NAME,
            emitted_monotonic_ns=time.monotonic_ns(),
            applied=True,
            dry_run=True,
            neutralization_reason=reason,
            detail="released held inputs; axes neutral (dry-run)",
            stage_status=PipelineStageStatus.DISABLED,
        )
        self.receipts.append(receipt)
        return receipt

    def close(self) -> None:
        if self.opened and not self.closed:
            self.neutralize("close")
        self.closed = True
