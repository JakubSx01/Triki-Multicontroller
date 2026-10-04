"""Frame parser interface and explicitly labeled synthetic decoder.

No measured CAP001 ProtocolDescriptor is enabled by default. The synthetic
decoder exists only for offline tests and the fake transport stream.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from triki_controller.core.models import (
    SCHEMA_VERSION,
    Notification,
    ParseDiagnostic,
    QualityFlags,
    RawSample,
)

# Explicitly synthetic — not measured CAP001 framing.
SYNTHETIC_REVISION = "synthetic-v0"
SYNTHETIC_MAGIC = b"TR"
SYNTHETIC_FRAME_LEN = 20  # magic(2) + body(18)
# body: ax ay az gx gy gz (6xh) + button (B) + tick (I) + flags (B) = 18 bytes
_BODY_STRUCT = struct.Struct("<6hBIB")


def _body_struct() -> struct.Struct:
    return _BODY_STRUCT


@dataclass(frozen=True, slots=True)
class ProtocolDescriptor:
    """Framing descriptor with explicit evidence quality.

    Slice 1 ships synthetic-v0 for offline tests. ``reference-hypothesis`` is a
    TrikiScope-derived provisional layout (**not measured**). Measured CAP001
    descriptors must come from HOM-27 fixtures and fail closed when unknown.
    """

    revision: str
    characteristic_uuid: str
    frame_size: int
    endianness: str
    synthetic: bool
    not_measured: bool = False

    @classmethod
    def synthetic_v0(cls) -> ProtocolDescriptor:
        return cls(
            revision=SYNTHETIC_REVISION,
            characteristic_uuid="0000fff1-0000-1000-8000-00805f9b34fb",
            frame_size=SYNTHETIC_FRAME_LEN,
            endianness="little",
            synthetic=True,
            not_measured=False,
        )

    @classmethod
    def cap001_reference_hypothesis(cls) -> ProtocolDescriptor:
        """TrikiScope 14 B ``22``/status framing — provisional, not HOM-27 measured."""
        return cls(
            revision="reference-hypothesis",
            characteristic_uuid="6e400003-b5a3-f393-e0a9-e50e24dcca9e",
            frame_size=14,
            endianness="little",
            synthetic=False,
            not_measured=True,
        )


def encode_synthetic_frame(
    *,
    accel: tuple[int, int, int],
    gyro: tuple[int, int, int],
    button: bool,
    device_tick: int,
    flags: int = 0,
) -> bytes:
    """Encode one SYNTHETIC_V0 frame for fake transport / tests."""
    body = _body_struct().pack(
        accel[0],
        accel[1],
        accel[2],
        gyro[0],
        gyro[1],
        gyro[2],
        1 if button else 0,
        device_tick & 0xFFFFFFFF,
        flags & 0xFF,
    )
    return SYNTHETIC_MAGIC + body


@runtime_checkable
class FrameParser(Protocol):
    def feed(self, notification: Notification) -> list[RawSample | ParseDiagnostic]:
        ...

    def reset(self, epoch: int) -> None:
        ...


class SyntheticFrameParser:
    """Buffers fragmented SYNTHETIC_V0 frames; resets on connection epoch change.

    Label: synthetic. Not a CAP001 measured decoder.
    """

    def __init__(
        self,
        *,
        descriptor: ProtocolDescriptor | None = None,
        max_buffer_bytes: int = 4096,
    ) -> None:
        self._descriptor = descriptor or ProtocolDescriptor.synthetic_v0()
        if not self._descriptor.synthetic:
            raise ValueError("SyntheticFrameParser only accepts synthetic descriptors")
        self._max_buffer_bytes = max_buffer_bytes
        self._buffer = bytearray()
        self._epoch: int | None = None
        self._sample_seq = 0
        self._pending_notification_seqs: list[int] = []

    def reset(self, epoch: int) -> None:
        """Discard pending bytes for a new connection epoch."""
        self._buffer.clear()
        self._pending_notification_seqs.clear()
        self._epoch = epoch
        # sample_seq continues across epochs within a session for uniqueness,
        # but buffers never mix — tested via incomplete frame discarded on reset.

    def feed(self, notification: Notification) -> list[RawSample | ParseDiagnostic]:
        out: list[RawSample | ParseDiagnostic] = []
        if self._epoch is None:
            self._epoch = notification.connection_epoch
        elif notification.connection_epoch != self._epoch:
            discarded = len(self._buffer)
            self.reset(notification.connection_epoch)
            if discarded:
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=(notification.notification_seq,),
                        kind="epoch_reset",
                        detail="Discarded pending parser buffer on connection_epoch change",
                        discarded_bytes=discarded,
                    )
                )

        if len(self._buffer) + len(notification.payload) > self._max_buffer_bytes:
            discarded = len(self._buffer) + len(notification.payload)
            self._buffer.clear()
            self._pending_notification_seqs.clear()
            out.append(
                ParseDiagnostic(
                    schema_version=SCHEMA_VERSION,
                    session_id=notification.session_id,
                    connection_epoch=notification.connection_epoch,
                    received_monotonic_ns=notification.received_monotonic_ns,
                    source_notification_seqs=(notification.notification_seq,),
                    kind="buffer_overflow",
                    detail="Parser buffer exceeded bound; discarded",
                    discarded_bytes=discarded,
                )
            )
            return out

        self._buffer.extend(notification.payload)
        self._pending_notification_seqs.append(notification.notification_seq)

        while True:
            idx = self._buffer.find(SYNTHETIC_MAGIC)
            if idx < 0:
                # No magic — keep a tiny tail in case magic straddles notifications.
                if len(self._buffer) > 1:
                    discarded = len(self._buffer) - 1
                    del self._buffer[:-1]
                    out.append(
                        ParseDiagnostic(
                            schema_version=SCHEMA_VERSION,
                            session_id=notification.session_id,
                            connection_epoch=notification.connection_epoch,
                            received_monotonic_ns=notification.received_monotonic_ns,
                            source_notification_seqs=tuple(self._pending_notification_seqs),
                            kind="resync",
                            detail="No SYNTHETIC_V0 magic found; discarded leading bytes",
                            discarded_bytes=discarded,
                        )
                    )
                    self._pending_notification_seqs = (
                        [self._pending_notification_seqs[-1]]
                        if self._pending_notification_seqs
                        else []
                    )
                break

            if idx > 0:
                discarded = idx
                del self._buffer[:idx]
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=tuple(self._pending_notification_seqs),
                        kind="resync",
                        detail="Skipped bytes before SYNTHETIC_V0 magic",
                        discarded_bytes=discarded,
                    )
                )

            if len(self._buffer) < SYNTHETIC_FRAME_LEN:
                # Incomplete frame — wait for more bytes (or epoch reset).
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=tuple(self._pending_notification_seqs),
                        kind="incomplete_frame",
                        detail=(
                            f"Buffered {len(self._buffer)}/{SYNTHETIC_FRAME_LEN} "
                            "bytes for SYNTHETIC_V0 frame"
                        ),
                        discarded_bytes=0,
                    )
                )
                break

            frame = bytes(self._buffer[:SYNTHETIC_FRAME_LEN])
            del self._buffer[:SYNTHETIC_FRAME_LEN]
            source_seqs = tuple(self._pending_notification_seqs)
            if self._buffer:
                # Remaining bytes may belong to later notifications in buffer;
                # keep the latest notification seq for provenance continuity.
                self._pending_notification_seqs = [source_seqs[-1]] if source_seqs else []
            else:
                self._pending_notification_seqs.clear()

            try:
                sample = self._decode_frame(
                    frame=frame,
                    notification=notification,
                    source_seqs=source_seqs,
                )
                out.append(sample)
            except struct.error as exc:
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=source_seqs,
                        kind="corrupt_frame",
                        detail=f"Failed to decode SYNTHETIC_V0 frame: {exc}",
                        discarded_bytes=len(frame),
                    )
                )

        return out

    def _decode_frame(
        self,
        *,
        frame: bytes,
        notification: Notification,
        source_seqs: tuple[int, ...],
    ) -> RawSample:
        body = frame[2:]
        ax, ay, az, gx, gy, gz, button_u8, tick, _flags = _body_struct().unpack(body)
        self._sample_seq += 1
        button: bool | None
        if button_u8 in (0, 1):
            button = bool(button_u8)
        else:
            button = None
        return RawSample(
            schema_version=SCHEMA_VERSION,
            session_id=notification.session_id,
            connection_epoch=notification.connection_epoch,
            sample_seq=self._sample_seq,
            received_monotonic_ns=notification.received_monotonic_ns,
            source_notification_seqs=source_seqs,
            protocol_revision=self._descriptor.revision,
            raw_frame=frame,
            accel_counts=(ax, ay, az),
            gyro_counts=(gx, gy, gz),
            button=button,
            device_tick=int(tick),
            battery_percent=None,
            rssi_dbm=None,
            quality_flags=QualityFlags(synthetic=True),
        )


class DisabledFrameParser:
    """Default parser: fails closed — no guessed CAP001 decoder."""

    def feed(self, notification: Notification) -> list[RawSample | ParseDiagnostic]:
        return [
            ParseDiagnostic(
                schema_version=SCHEMA_VERSION,
                session_id=notification.session_id,
                connection_epoch=notification.connection_epoch,
                received_monotonic_ns=notification.received_monotonic_ns,
                source_notification_seqs=(notification.notification_seq,),
                kind="decoder_disabled",
                detail=(
                    "No measured ProtocolDescriptor enabled. "
                    "Use SyntheticFrameParser explicitly for offline tests."
                ),
                discarded_bytes=len(notification.payload),
            )
        ]

    def reset(self, epoch: int) -> None:
        return None
