"""CAP001 reference-hypothesis frame parser (TrikiScope-derived, not measured).

Provisional adapter only. Framing matches TrikiScope's 14-byte ``22``/status
layout from clone commit 8ad3764. This is **not** HOM-27 measured evidence and
must not be treated as a validated CAP001 protocol descriptor.

Derived from TrikiScope ``trikiscope/protocol.py`` (MIT License).
Copyright (c) 2026 Mateusz "Maku" Mączewski — see THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from triki_controller.core.models import (
    SCHEMA_VERSION,
    Notification,
    ParseDiagnostic,
    QualityFlags,
    RawSample,
)
from triki_controller.protocol.parser import ProtocolDescriptor

# Nordic UART Service TX (device -> host) — TrikiScope reference, not measured here.
NUS_TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"

REFERENCE_HYPOTHESIS_REVISION = "reference-hypothesis"
FRAME_LENGTH = 14
FRAME_HEADER_BYTE0 = 0x22
FRAME_STATUS_BYTES = frozenset({0x00, 0x01})
_AXIS_STRUCT = struct.Struct("<6h")

# Quality label required by HOM-34 — never claim measured CAP001 evidence.
_NOT_MEASURED_NOTES = (
    "not measured",
    "TrikiScope reference-hypothesis (commit 8ad3764); pending HOM-27",
)


def encode_cap001_hypothesis_frame(
    *,
    gyro: tuple[int, int, int],
    accel: tuple[int, int, int],
    button: bool = False,
) -> bytes:
    """Encode one 14-byte TrikiScope-shaped frame for offline tests."""
    status = 0x01 if button else 0x00
    body = _AXIS_STRUCT.pack(gyro[0], gyro[1], gyro[2], accel[0], accel[1], accel[2])
    return bytes([FRAME_HEADER_BYTE0, status]) + body


class Cap001HypothesisFrameParser:
    """Buffers fragmented 14 B ``22``/status frames; resets on connection epoch.

    Label: reference-hypothesis / **not measured**. Not a HOM-27 validated decoder.
    """

    def __init__(
        self,
        *,
        descriptor: ProtocolDescriptor | None = None,
        max_buffer_bytes: int = 4096,
    ) -> None:
        self._descriptor = descriptor or ProtocolDescriptor.cap001_reference_hypothesis()
        if self._descriptor.revision != REFERENCE_HYPOTHESIS_REVISION:
            raise ValueError(
                "Cap001HypothesisFrameParser requires revision "
                f"{REFERENCE_HYPOTHESIS_REVISION!r}"
            )
        if self._descriptor.synthetic:
            raise ValueError("Cap001HypothesisFrameParser rejects synthetic descriptors")
        self._max_buffer_bytes = max_buffer_bytes
        self._buffer = bytearray()
        self._epoch: int | None = None
        self._sample_seq = 0
        self._pending_notification_seqs: list[int] = []

    def reset(self, epoch: int) -> None:
        self._buffer.clear()
        self._pending_notification_seqs.clear()
        self._epoch = epoch

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
            header_index = self._find_header()
            if header_index < 0:
                if self._buffer:
                    keep_trailing = self._buffer[-1] == FRAME_HEADER_BYTE0
                    drop_count = len(self._buffer) - 1 if keep_trailing else len(self._buffer)
                    if drop_count:
                        out.append(
                            ParseDiagnostic(
                                schema_version=SCHEMA_VERSION,
                                session_id=notification.session_id,
                                connection_epoch=notification.connection_epoch,
                                received_monotonic_ns=notification.received_monotonic_ns,
                                source_notification_seqs=tuple(self._pending_notification_seqs),
                                kind="resync",
                                detail=(
                                    "No 22/status header found; discarded leading bytes "
                                    "(reference-hypothesis, not measured)"
                                ),
                                discarded_bytes=drop_count,
                            )
                        )
                    if keep_trailing:
                        trailing = self._buffer[-1]
                        self._buffer.clear()
                        self._buffer.append(trailing)
                        self._pending_notification_seqs = (
                            [self._pending_notification_seqs[-1]]
                            if self._pending_notification_seqs
                            else []
                        )
                    else:
                        self._buffer.clear()
                        self._pending_notification_seqs.clear()
                break

            if header_index > 0:
                discarded = header_index
                del self._buffer[:header_index]
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=tuple(self._pending_notification_seqs),
                        kind="resync",
                        detail="Skipped bytes before 22/status header (not measured)",
                        discarded_bytes=discarded,
                    )
                )

            if len(self._buffer) < FRAME_LENGTH:
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=tuple(self._pending_notification_seqs),
                        kind="incomplete_frame",
                        detail=(
                            f"Buffered {len(self._buffer)}/{FRAME_LENGTH} bytes "
                            "for reference-hypothesis frame"
                        ),
                        discarded_bytes=0,
                    )
                )
                break

            frame = bytes(self._buffer[:FRAME_LENGTH])
            del self._buffer[:FRAME_LENGTH]
            source_seqs = tuple(self._pending_notification_seqs)
            if self._buffer:
                self._pending_notification_seqs = [source_seqs[-1]] if source_seqs else []
            else:
                self._pending_notification_seqs.clear()

            try:
                out.append(
                    self._decode_frame(
                        frame=frame,
                        notification=notification,
                        source_seqs=source_seqs,
                    )
                )
            except struct.error as exc:
                out.append(
                    ParseDiagnostic(
                        schema_version=SCHEMA_VERSION,
                        session_id=notification.session_id,
                        connection_epoch=notification.connection_epoch,
                        received_monotonic_ns=notification.received_monotonic_ns,
                        source_notification_seqs=source_seqs,
                        kind="corrupt_frame",
                        detail=f"Failed to decode reference-hypothesis frame: {exc}",
                        discarded_bytes=len(frame),
                    )
                )

        return out

    def _find_header(self) -> int:
        buffer = self._buffer
        start = 0
        while True:
            idx = buffer.find(FRAME_HEADER_BYTE0, start)
            if idx < 0 or idx + 1 >= len(buffer):
                return -1
            if buffer[idx + 1] in FRAME_STATUS_BYTES:
                return idx
            start = idx + 1

    def _decode_frame(
        self,
        *,
        frame: bytes,
        notification: Notification,
        source_seqs: tuple[int, ...],
    ) -> RawSample:
        status = frame[1]
        gx, gy, gz, ax, ay, az = _AXIS_STRUCT.unpack_from(frame, 2)
        self._sample_seq += 1
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
            button=bool(status & 0x01),
            device_tick=None,
            battery_percent=None,
            rssi_dbm=None,
            quality_flags=QualityFlags(
                not_measured=True,
                notes=_NOT_MEASURED_NOTES,
            ),
        )
