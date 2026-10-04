"""Offline unittests for CAP001 reference-hypothesis parser (not measured).

Crafted 14-byte ``22``/status frames only — no Bleak / hardware required.
"""

from __future__ import annotations

import unittest

from triki_controller.core.models import (
    SCHEMA_VERSION,
    Notification,
    ParseDiagnostic,
    RawSample,
)
from triki_controller.protocol.cap001_hypothesis import (
    FRAME_LENGTH,
    REFERENCE_HYPOTHESIS_REVISION,
    Cap001HypothesisFrameParser,
    encode_cap001_hypothesis_frame,
)
from triki_controller.protocol.parser import ProtocolDescriptor
from triki_controller.runtime.controller import RuntimeController
from triki_controller.transport.ble import BleTransport


def _notif(
    *,
    payload: bytes,
    epoch: int = 1,
    seq: int = 1,
    session_id: str = "sess-hyp",
    t_ns: int = 2_000_000_000,
) -> Notification:
    return Notification(
        schema_version=SCHEMA_VERSION,
        session_id=session_id,
        connection_epoch=epoch,
        notification_seq=seq,
        received_monotonic_ns=t_ns,
        characteristic_uuid="6e400003-b5a3-f393-e0a9-e50e24dcca9e",
        payload=payload,
    )


class Cap001HypothesisParserTests(unittest.TestCase):
    """NOT MEASURED — TrikiScope reference-hypothesis framing only."""

    def test_descriptor_labeled_not_measured(self) -> None:
        desc = ProtocolDescriptor.cap001_reference_hypothesis()
        self.assertEqual(desc.revision, REFERENCE_HYPOTHESIS_REVISION)
        self.assertTrue(desc.not_measured)
        self.assertFalse(desc.synthetic)
        self.assertEqual(desc.frame_size, FRAME_LENGTH)

    def test_exact_14_byte_frame_integers(self) -> None:
        parser = Cap001HypothesisFrameParser()
        frame = encode_cap001_hypothesis_frame(
            gyro=(-100, 200, -300),
            accel=(1000, -2000, 3000),
            button=True,
        )
        self.assertEqual(len(frame), 14)
        self.assertEqual(frame[0], 0x22)
        self.assertEqual(frame[1], 0x01)
        results = parser.feed(_notif(payload=frame))
        samples = [r for r in results if isinstance(r, RawSample)]
        self.assertEqual(len(samples), 1)
        s = samples[0]
        self.assertEqual(s.gyro_counts, (-100, 200, -300))
        self.assertEqual(s.accel_counts, (1000, -2000, 3000))
        self.assertIs(s.button, True)
        self.assertIsNone(s.device_tick)
        self.assertIsNone(s.battery_percent)
        self.assertIsNone(s.rssi_dbm)
        self.assertEqual(s.raw_frame, frame)
        self.assertEqual(s.protocol_revision, REFERENCE_HYPOTHESIS_REVISION)
        self.assertTrue(s.quality_flags.not_measured)
        self.assertFalse(s.quality_flags.synthetic)
        self.assertIn("not measured", s.quality_flags.notes)

    def test_button_released_status_byte(self) -> None:
        parser = Cap001HypothesisFrameParser()
        frame = encode_cap001_hypothesis_frame(
            gyro=(0, 0, 0),
            accel=(1, 2, 3),
            button=False,
        )
        self.assertEqual(frame[1], 0x00)
        samples = [r for r in parser.feed(_notif(payload=frame)) if isinstance(r, RawSample)]
        self.assertEqual(len(samples), 1)
        self.assertIs(samples[0].button, False)

    def test_split_and_coalesced_frames(self) -> None:
        parser = Cap001HypothesisFrameParser()
        f1 = encode_cap001_hypothesis_frame(gyro=(1, 2, 3), accel=(4, 5, 6), button=False)
        f2 = encode_cap001_hypothesis_frame(gyro=(7, 8, 9), accel=(10, 11, 12), button=True)

        mid = 6
        partial = parser.feed(_notif(payload=f1[:mid], seq=1))
        self.assertTrue(any(isinstance(r, ParseDiagnostic) and r.kind == "incomplete_frame" for r in partial))

        rest = parser.feed(_notif(payload=f1[mid:] + f2, seq=2, t_ns=2_000_000_100))
        samples = [r for r in rest if isinstance(r, RawSample)]
        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].accel_counts, (4, 5, 6))
        self.assertEqual(samples[1].accel_counts, (10, 11, 12))
        self.assertIs(samples[1].button, True)
        self.assertEqual(samples[0].source_notification_seqs, (1, 2))

    def test_resync_skips_garbage_keeps_valid_frame(self) -> None:
        parser = Cap001HypothesisFrameParser()
        good = encode_cap001_hypothesis_frame(gyro=(0, 0, 0), accel=(9, 8, 7), button=False)
        results = parser.feed(_notif(payload=b"\xff\x00GARBAGE" + good))
        diags = [r for r in results if isinstance(r, ParseDiagnostic)]
        samples = [r for r in results if isinstance(r, RawSample)]
        self.assertTrue(any(d.kind == "resync" for d in diags))
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].accel_counts, (9, 8, 7))

    def test_epoch_reset_discards_pending_bytes(self) -> None:
        parser = Cap001HypothesisFrameParser()
        frame = encode_cap001_hypothesis_frame(gyro=(1, 1, 1), accel=(2, 2, 2), button=False)
        parser.feed(_notif(payload=frame[:5], epoch=1, seq=1))
        results = parser.feed(_notif(payload=frame, epoch=2, seq=2, t_ns=3_000_000_000))
        diags = [r for r in results if isinstance(r, ParseDiagnostic)]
        samples = [r for r in results if isinstance(r, RawSample)]
        self.assertTrue(any(d.kind == "epoch_reset" and d.discarded_bytes == 5 for d in diags))
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].connection_epoch, 2)

    def test_runtime_controller_with_hypothesis_parser(self) -> None:
        controller = RuntimeController(parser=Cap001HypothesisFrameParser())
        frame = encode_cap001_hypothesis_frame(gyro=(0, 0, 0), accel=(1, 0, -1), button=True)
        items = controller.handle_notification(_notif(payload=frame))
        samples = [i for i in items if isinstance(i, RawSample)]
        self.assertEqual(len(samples), 1)
        self.assertEqual(controller.stats.samples, 1)
        self.assertTrue(samples[0].quality_flags.not_measured)


class BleTransportImportTests(unittest.TestCase):
    """Offline: BleTransport module imports without bleak installed."""

    def test_ble_transport_class_importable(self) -> None:
        self.assertTrue(callable(BleTransport))

    def test_missing_bleak_raises_clear_error(self) -> None:
        # Force the helper path: if bleak is installed this still documents the message shape.
        from triki_controller.transport import ble as ble_mod

        try:
            import bleak  # noqa: F401
        except ImportError:
            with self.assertRaises(ImportError) as ctx:
                ble_mod._require_bleak()
            self.assertIn("triki-controller[ble]", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
