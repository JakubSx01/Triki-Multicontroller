"""Transport protocol — no scaling or profile loading."""

from __future__ import annotations

from typing import AsyncIterator, Protocol, runtime_checkable

from triki_controller.core.models import ConnectionEvent, Notification


@runtime_checkable
class Transport(Protocol):
    def events(self) -> AsyncIterator[Notification | ConnectionEvent]:
        ...

    async def disconnect(self) -> None:
        ...
