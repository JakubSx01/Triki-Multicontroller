"""Output backend interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from triki_controller.core.models import MappedState, OutputReceipt


@runtime_checkable
class OutputBackend(Protocol):
    def open(self, capabilities: dict[str, object]) -> None:
        ...

    def apply(self, state: MappedState) -> OutputReceipt:
        ...

    def neutralize(self, reason: str) -> OutputReceipt:
        ...

    def close(self) -> None:
        ...
