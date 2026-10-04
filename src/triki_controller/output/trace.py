"""In-memory output. Records desired controls and neutralizes them. No uinput."""

from __future__ import annotations

import time

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    OutputReceipt,
    PipelineStageStatus,
)
from triki_controller.output.mpris_volume import MprisPlayerVolume


class TraceOutput:
    """Dry-run sink for emulator tests and `emulate` without `--live`."""

    BACKEND_NAME = "trace-dry-run"

    def __init__(self, *, history_limit: int | None = None) -> None:
        self.history_limit = history_limit
        self.opened = False
        self.closed = False
        self.receipts: list[OutputReceipt] = []
        self.held_buttons: set[str] = set()
        self.axes: dict[str, float] = {}
        self.deltas: list[dict[str, float]] = []
        self.pulses: list[str] = []
        self._epoch = 0
        self._dirty = False
        self._mpris: MprisPlayerVolume | None = None

    def open(self, capabilities: dict[str, object]) -> None:
        if capabilities.get("claim_uinput"):
            raise RuntimeError("TraceOutput refuses uinput claims")
        self.opened = True
        self.closed = False
        self._epoch = int(capabilities.get("activation_epoch", 1))
        self.held_buttons.clear()
        self.axes.clear()
        self._neutral_axes(capabilities.get("mode"))
        self._mpris = (
            MprisPlayerVolume(dry_run=True) if capabilities.get("mode") == "media" else None
        )
        self._dirty = True

    def apply(self, state: MappedState) -> OutputReceipt:
        if not self.opened or self.closed:
            raise RuntimeError("TraceOutput is not open")
        if state.activation_epoch != self._epoch:
            return self._receipt(
                state,
                applied=False,
                reason=None,
                detail=f"stale activation_epoch {state.activation_epoch}!={self._epoch}",
            )
        self.held_buttons = set(state.held_buttons) | set(state.held_keys)
        for name, value in state.absolute_axes.items():
            self.axes[name] = value
        if state.relative_deltas:
            self.deltas.append(dict(state.relative_deltas))
        self.pulses.extend(state.pulses)
        notes: list[str] = []
        if self._mpris is not None:
            level = state.absolute_axes.get("player_volume")
            if level is not None:
                err = self._mpris.apply_level(float(level))
                if err:
                    notes.append(err)
            for pulse in state.pulses:
                if self._mpris.handles(pulse):
                    err = self._mpris.apply_pulse(pulse)
                    if err:
                        notes.append(err)
                elif self._mpris.handles_transport(pulse):
                    err = self._mpris.apply_transport(pulse)
                    if err:
                        notes.append(err)
        self._dirty = True
        self._trim()
        detail = "dry-run apply"
        if self._mpris is not None:
            detail = "dry-run apply (mpris volume logged only)"
        if notes:
            detail += "; " + "; ".join(notes)
        return self._receipt(state, applied=True, reason=None, detail=detail)
    def _trim(self) -> None:
        limit = self.history_limit
        if limit is None:
            return
        for history in (self.receipts, self.deltas, self.pulses):
            if len(history) > 2 * limit:
                del history[:-limit]

    def neutralize(self, reason: str) -> OutputReceipt:
        self.held_buttons.clear()
        for name in list(self.axes):
            self.axes[name] = 0.0
        self._dirty = False
        self._epoch += 1
        receipt = OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id="",
            raw_connection_epoch=0,
            raw_sample_seq=0,
            activation_epoch=self._epoch,
            backend=self.BACKEND_NAME,
            emitted_monotonic_ns=time.monotonic_ns(),
            applied=True,
            dry_run=True,
            neutralization_reason=reason,
            detail="released held inputs; axes neutral (dry-run)",
            stage_status=PipelineStageStatus.AVAILABLE,
        )
        self.receipts.append(receipt)
        return receipt

    def close(self) -> None:
        if self.opened and not self.closed and self._dirty:
            self.neutralize("close")
        self.closed = True

    def _neutral_axes(self, mode: object) -> None:
        if mode == "steering":
            self.axes = {"wheel": 0.0, "throttle": 0.0, "brake": 0.0}

    def _receipt(
        self,
        state: MappedState,
        *,
        applied: bool,
        reason: str | None,
        detail: str,
    ) -> OutputReceipt:
        receipt = OutputReceipt(
            schema_version=SCHEMA_VERSION,
            raw_session_id=state.raw_session_id,
            raw_connection_epoch=state.raw_connection_epoch,
            raw_sample_seq=state.raw_sample_seq,
            activation_epoch=state.activation_epoch,
            backend=self.BACKEND_NAME,
            emitted_monotonic_ns=time.monotonic_ns(),
            applied=applied,
            dry_run=True,
            neutralization_reason=reason,
            detail=detail,
            stage_status=PipelineStageStatus.AVAILABLE,
        )
        self.receipts.append(receipt)
        return receipt
