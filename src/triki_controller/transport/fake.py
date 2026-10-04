"""Deterministic fake BLE transport for offline monitor/record and tests.

Emits ConnectionEvent + Notification with SYNTHETIC_V0 payloads.
Does not claim physical CAP001 support.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import AsyncIterator

from triki_controller.core.models import (
    SCHEMA_VERSION,
    ConnectionEvent,
    ConnectionState,
    Notification,
)
from triki_controller.protocol.parser import (
    ProtocolDescriptor,
    encode_synthetic_frame,
)


@dataclass(frozen=True, slots=True)
class SyntheticStreamSpec:
    """Deterministic sample plan for the fake transport."""

    sample_count: int = 8
    reconnect_after: int | None = None  # emit disconnect/reconnect after N samples
    include_malformed: bool = False
    split_frames: bool = False
    coalesce_frames: bool = False
    base_monotonic_ns: int = 1_000_000_000
    notification_gap_ns: int = 10_000_000  # 10 ms


class FakeTransport:
    """Async iterator of synthetic connection + notification events."""

    def __init__(
        self,
        *,
        session_id: str,
        spec: SyntheticStreamSpec | None = None,
        descriptor: ProtocolDescriptor | None = None,
    ) -> None:
        self._session_id = session_id
        self._spec = spec or SyntheticStreamSpec()
        self._descriptor = descriptor or ProtocolDescriptor.synthetic_v0()
        self._disconnected = False
        self._event_seq = 0
        self._notification_seq = 0
        self._connection_epoch = 0

    async def disconnect(self) -> None:
        self._disconnected = True

    def events(self) -> AsyncIterator[Notification | ConnectionEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[Notification | ConnectionEvent]:
        spec = self._spec
        yield self._connection(ConnectionState.SCANNING, "fake scan start")
        if self._disconnected:
            yield self._connection(ConnectionState.DISCONNECTED, "disconnect before connect")
            return
        yield self._connection(ConnectionState.CONNECTING, "fake connect")
        self._connection_epoch = 1
        yield self._connection(ConnectionState.STREAMING, "subscribed (fake)")

        samples_emitted = 0
        i = 0
        while samples_emitted < spec.sample_count:
            if self._disconnected:
                yield self._connection(ConnectionState.DISCONNECTED, "user disconnect")
                return

            if spec.reconnect_after is not None and samples_emitted == spec.reconnect_after:
                yield self._connection(ConnectionState.DISCONNECTED, "simulated drop")
                yield self._connection(ConnectionState.CONNECTING, "fake reconnect")
                self._connection_epoch += 1
                yield self._connection(ConnectionState.STREAMING, "resubscribed (fake)")

            if spec.include_malformed and i == 0:
                # Corrupt leading bytes then a valid frame in later iteration.
                yield self._notification(
                    payload=b"\xff\x00BAD",
                    index=i,
                )
                i += 1
                continue

            accel = (100 + samples_emitted, -200 - samples_emitted, 300 + samples_emitted * 2)
            gyro = (10 - samples_emitted, 20 + samples_emitted, -30)
            button = samples_emitted % 3 == 0
            tick = 1000 + samples_emitted
            frame = encode_synthetic_frame(
                accel=accel,
                gyro=gyro,
                button=button,
                device_tick=tick,
            )

            if spec.split_frames and samples_emitted % 2 == 0:
                mid = len(frame) // 2
                yield self._notification(payload=frame[:mid], index=i)
                i += 1
                await asyncio.sleep(0)
                if self._disconnected:
                    yield self._connection(ConnectionState.DISCONNECTED, "user disconnect")
                    return
                yield self._notification(payload=frame[mid:], index=i)
                i += 1
                samples_emitted += 1
            elif spec.coalesce_frames and samples_emitted + 1 < spec.sample_count:
                frame2 = encode_synthetic_frame(
                    accel=(accel[0] + 1, accel[1], accel[2]),
                    gyro=gyro,
                    button=False,
                    device_tick=tick + 1,
                )
                yield self._notification(payload=frame + frame2, index=i)
                i += 1
                samples_emitted += 2
            else:
                yield self._notification(payload=frame, index=i)
                i += 1
                samples_emitted += 1

            await asyncio.sleep(0)

        if not self._disconnected:
            yield self._connection(ConnectionState.DISCONNECTED, "stream complete")

    def _connection(self, state: ConnectionState, reason: str) -> ConnectionEvent:
        self._event_seq += 1
        return ConnectionEvent(
            schema_version=SCHEMA_VERSION,
            session_id=self._session_id,
            connection_epoch=self._connection_epoch,
            event_seq=self._event_seq,
            host_monotonic_ns=self._spec.base_monotonic_ns + self._event_seq,
            state=state,
            reason=reason,
        )

    def _notification(self, *, payload: bytes, index: int) -> Notification:
        self._notification_seq += 1
        return Notification(
            schema_version=SCHEMA_VERSION,
            session_id=self._session_id,
            connection_epoch=self._connection_epoch,
            notification_seq=self._notification_seq,
            received_monotonic_ns=(
                self._spec.base_monotonic_ns
                + 1_000_000
                + index * self._spec.notification_gap_ns
            ),
            characteristic_uuid=self._descriptor.characteristic_uuid,
            payload=payload,
        )
