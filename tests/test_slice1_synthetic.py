"""Focused unittests for slice 1 — all parser/stream tests labeled synthetic."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from triki_controller.core.models import (
    SCHEMA_VERSION,
    ConnectionEvent,
    ConnectionState,
    Notification,
    ParseDiagnostic,
    RawSample,
)
from triki_controller.protocol.parser import (
    SYNTHETIC_REVISION,
    DisabledFrameParser,
    SyntheticFrameParser,
    encode_synthetic_frame,
)
from triki_controller.recording.csv_export import RawCsvReader, RawCsvWriter, SessionSidecar
from triki_controller.runtime.controller import RuntimeController
from triki_controller.transport.fake import FakeTransport, SyntheticStreamSpec


def _notif(
    *,
    payload: bytes,
    epoch: int = 1,
    seq: int = 1,
    session_id: str = "sess-test",
    t_ns: int = 1_000_000_000,
) -> Notification:
    return Notification(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        connection_epoch=epoch,
        notification_seq=seq,
        received_monotonic_ns=t_ns,
        characteristic_uuid="0000fff1-0000-1000-8000-00805f9b34fb",
        payload=payload,
    )


class SyntheticParserTests(unittest.TestCase):
    """SYNTHETIC — not measured CAP001 framing."""

    def test_exact_integers_and_null_battery_rssi(self) -> None:
        parser = SyntheticFrameParser()
        frame = encode_synthetic_frame(
            accel=(12345, -1, 0),
            gyro=(-32000, 7, 99),
            button=True,
            device_tick=42,
        )
        results = parser.feed(_notif(payload=frame))
        samples = [r for r in results if isinstance(r, RawSample)]
        self.assertEqual(len(samples), 1)
        s = samples[0]
        self.assertEqual(s.accel_counts, (12345, -1, 0))
        self.assertEqual(s.gyro_counts, (-32000, 7, 99))
        self.assertIs(s.button, True)
        self.assertEqual(s.device_tick, 42)
        self.assertIsNone(s.battery_percent)
        self.assertIsNone(s.rssi_dbm)
        self.assertEqual(s.raw_frame, frame)
        self.assertEqual(s.protocol_revision, SYNTHETIC_REVISION)
        self.assertTrue(s.quality_flags.synthetic)

    def test_incomplete_frame_diagnostic(self) -> None:
        parser = SyntheticFrameParser()
        frame = encode_synthetic_frame(
            accel=(1, 2, 3),
            gyro=(4, 5, 6),
            button=False,
            device_tick=1,
        )
        partial = frame[:10]
        results = parser.feed(_notif(payload=partial, seq=1))
        diags = [r for r in results if isinstance(r, ParseDiagnostic)]
        self.assertTrue(any(d.kind == "incomplete_frame" for d in diags))
        self.assertFalse(any(isinstance(r, RawSample) for r in results))

        # Complete with remaining bytes.
        results2 = parser.feed(_notif(payload=frame[10:], seq=2, t_ns=1_000_000_100))
        samples = [r for r in results2 if isinstance(r, RawSample)]
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].accel_counts, (1, 2, 3))
        self.assertEqual(samples[0].source_notification_seqs, (1, 2))

    def test_corrupt_leading_bytes_resync(self) -> None:
        parser = SyntheticFrameParser()
        good = encode_synthetic_frame(
            accel=(10, 20, 30),
            gyro=(0, 0, 0),
            button=False,
            device_tick=9,
        )
        results = parser.feed(_notif(payload=b"\xff\xffXX" + good))
        diags = [r for r in results if isinstance(r, ParseDiagnostic)]
        samples = [r for r in results if isinstance(r, RawSample)]
        self.assertTrue(any(d.kind == "resync" for d in diags))
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].accel_counts, (10, 20, 30))

    def test_reconnect_epochs_do_not_mix_buffers(self) -> None:
        parser = SyntheticFrameParser()
        frame = encode_synthetic_frame(
            accel=(1, 1, 1),
            gyro=(2, 2, 2),
            button=False,
            device_tick=1,
        )
        # Leave incomplete frame in epoch 1.
        parser.feed(_notif(payload=frame[:8], epoch=1, seq=1))
        # Epoch 2 must discard pending bytes.
        results = parser.feed(_notif(payload=frame, epoch=2, seq=2, t_ns=2_000_000_000))
        diags = [r for r in results if isinstance(r, ParseDiagnostic)]
        samples = [r for r in results if isinstance(r, RawSample)]
        self.assertTrue(any(d.kind == "epoch_reset" and d.discarded_bytes == 8 for d in diags))
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].connection_epoch, 2)
        self.assertEqual(samples[0].accel_counts, (1, 1, 1))

    def test_disabled_parser_fails_closed(self) -> None:
        parser = DisabledFrameParser()
        frame = encode_synthetic_frame(
            accel=(0, 0, 0),
            gyro=(0, 0, 0),
            button=False,
            device_tick=0,
        )
        results = parser.feed(_notif(payload=frame))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], ParseDiagnostic)
        assert isinstance(results[0], ParseDiagnostic)
        self.assertEqual(results[0].kind, "decoder_disabled")


class SyntheticCsvRoundTripTests(unittest.TestCase):
    """SYNTHETIC — CSV preserves integers, timestamps, bytes, nulls."""

    def test_csv_round_trip_preserves_raw_fields(self) -> None:
        sample = RawSample(
            schema_version=SCHEMA_VERSION,
            session_id="sess-csv",
            connection_epoch=2,
            sample_seq=7,
            received_monotonic_ns=9_876_543_210,
            source_notification_seqs=(3, 4),
            protocol_revision=SYNTHETIC_REVISION,
            raw_frame=encode_synthetic_frame(
                accel=(111, -222, 333),
                gyro=(-4, 5, -6),
                button=True,
                device_tick=55,
            ),
            accel_counts=(111, -222, 333),
            gyro_counts=(-4, 5, -6),
            button=True,
            device_tick=55,
            battery_percent=None,
            rssi_dbm=None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw_samples.csv"
            with RawCsvWriter(path) as writer:
                writer.write_sample(sample)
            text = path.read_text(encoding="utf-8")
            # Empty fields for null battery/rssi (consecutive commas).
            self.assertIn(",55,,,", text)
            loaded = RawCsvReader.read(path)
            self.assertEqual(len(loaded), 1)
            got = loaded[0]
            self.assertEqual(got.accel_counts, sample.accel_counts)
            self.assertEqual(got.gyro_counts, sample.gyro_counts)
            self.assertEqual(got.received_monotonic_ns, sample.received_monotonic_ns)
            self.assertEqual(got.raw_frame, sample.raw_frame)
            self.assertEqual(got.source_notification_seqs, sample.source_notification_seqs)
            self.assertIsNone(got.battery_percent)
            self.assertIsNone(got.rssi_dbm)
            self.assertIs(got.button, True)
            self.assertEqual(got.device_tick, 55)


class SyntheticFakeTransportTests(unittest.TestCase):
    """SYNTHETIC — fake stream + disconnect handling."""

    def test_monitor_stream_emits_connection_and_raw(self) -> None:
        async def run() -> None:
            transport = FakeTransport(
                session_id="sess-mon",
                spec=SyntheticStreamSpec(sample_count=3),
            )
            controller = RuntimeController()
            states: list[ConnectionState] = []
            samples: list[RawSample] = []
            async for event in transport.events():
                if isinstance(event, ConnectionEvent):
                    controller.handle_connection(event)
                    states.append(event.state)
                else:
                    for item in controller.handle_notification(event):
                        if isinstance(item, RawSample):
                            samples.append(item)
            self.assertIn(ConnectionState.STREAMING, states)
            self.assertIn(ConnectionState.DISCONNECTED, states)
            self.assertEqual(len(samples), 3)
            self.assertIsNone(samples[0].battery_percent)
            self.assertIsNone(samples[0].rssi_dbm)
            pipe = controller.pipeline_status().as_dict()
            self.assertEqual(pipe["RAW"], "available")
            self.assertEqual(pipe["FILTERED"], "unavailable")
            self.assertEqual(pipe["PROFILE_MAPPING"], "unavailable")
            self.assertEqual(pipe["FINAL_OUTPUT"], "disabled")

        asyncio.run(run())

    def test_disconnect_mid_stream_neutralizes(self) -> None:
        async def run() -> None:
            transport = FakeTransport(
                session_id="sess-disc",
                spec=SyntheticStreamSpec(sample_count=20),
            )
            controller = RuntimeController()
            controller.activate()
            count = 0
            async for event in transport.events():
                if isinstance(event, ConnectionEvent):
                    controller.handle_connection(event)
                else:
                    controller.handle_notification(event)
                    count += 1
                    if count >= 2:
                        await transport.disconnect()
            self.assertTrue(any(r.neutralization_reason for r in controller.output.receipts))
            self.assertEqual(controller.stats.last_state, ConnectionState.DISCONNECTED)

        asyncio.run(run())

    def test_reconnect_epochs_separate(self) -> None:
        async def run() -> None:
            transport = FakeTransport(
                session_id="sess-re",
                spec=SyntheticStreamSpec(sample_count=4, reconnect_after=2),
            )
            controller = RuntimeController()
            epochs: set[int] = set()
            async for event in transport.events():
                if isinstance(event, ConnectionEvent):
                    controller.handle_connection(event)
                else:
                    for item in controller.handle_notification(event):
                        if isinstance(item, RawSample):
                            epochs.add(item.connection_epoch)
            self.assertEqual(epochs, {1, 2})
            self.assertGreaterEqual(controller.stats.reconnects, 1)

        asyncio.run(run())

    def test_session_sidecar_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            sidecar = SessionSidecar(
                session_id="sess-side",
                started_at_utc="2026-10-01T00:00:00Z",
                recording_complete=True,
                sample_count=2,
            )
            sidecar.write(path)
            loaded = SessionSidecar.read(path)
            self.assertEqual(loaded.sample_count, 2)
            self.assertEqual(loaded.device_metadata["kind"], "fake_synthetic")


if __name__ == "__main__":
    unittest.main()
