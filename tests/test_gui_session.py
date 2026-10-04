"""Headless GUI glue: settings validation and ControllerSession. No display, no uinput."""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from triki_controller.core.models import SCHEMA_VERSION, ConnectionEvent, ConnectionState
from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import (
    GuiSettings,
    SettingsError,
    load_settings,
    parse_settings,
    save_settings,
)
from triki_controller.output.trace import TraceOutput
from triki_controller.runtime.synthetic import make_raw, pose_level


class _FakeLive(TraceOutput):
    def open(self, capabilities: dict[str, object]) -> None:
        super().open({**capabilities, "claim_uinput": False})


class _Factory:
    def __init__(self, *, live_error: Exception | None = None) -> None:
        self.created: list[tuple[bool, TraceOutput]] = []
        self.live_error = live_error

    def __call__(self, live: bool) -> TraceOutput:
        if live and self.live_error is not None:
            raise self.live_error
        output = _FakeLive() if live else TraceOutput()
        self.created.append((live, output))
        return output


def _wait(predicate, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _pump(session: ControllerSession) -> None:
    """Feed synthetic samples until disconnect, without a product demo mode."""
    conn_id = session._conn_id
    session._transport = "ble"
    session._on_connection(
        conn_id,
        ConnectionEvent(
            schema_version=SCHEMA_VERSION,
            session_id="t",
            connection_epoch=1,
            event_seq=1,
            host_monotonic_ns=0,
            state=ConnectionState.STREAMING,
            reason="test",
        ),
    )

    def run() -> None:
        seq = 0
        while True:
            seq += 1
            if not session._on_sample(
                conn_id,
                make_raw(accel=pose_level(), seq=seq, t_ns=seq * 20_000_000),
            ):
                return
            time.sleep(0.002)

    threading.Thread(target=run, name="triki-test-pump", daemon=True).start()


def _stream(session: ControllerSession) -> int:
    conn_id = session._conn_id
    session._on_connection(
        conn_id,
        ConnectionEvent(
            schema_version=SCHEMA_VERSION,
            session_id="t",
            connection_epoch=1,
            event_seq=1,
            host_monotonic_ns=0,
            state=ConnectionState.STREAMING,
            reason="test",
        ),
    )
    return conn_id


def _feed(session: ControllerSession, conn_id: int, gyros, *, start_seq: int, start_ns: int) -> int:
    t_ns = start_ns
    for index, gyro in enumerate(gyros):
        t_ns = start_ns + index * 20_000_000
        session._on_sample(
            conn_id, make_raw(accel=pose_level(), gyro=gyro, seq=start_seq + index, t_ns=t_ns)
        )
    return t_ns


class SettingsTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        settings = GuiSettings(
            profile="mouse",
            orientation="yaw_90",
            invert_pitch=True,
            thresholds={
                "mouse": {
                    "deadzone_deg": 3.0,
                    "mouse_x_px_per_sec": 1200.0,
                    "mouse_y_px_per_sec": 800.0,
                    "mouse_x_sign": -1.0,
                    "mouse_y_sign": 1.0,
                }
            },
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "gui-settings.json"
            save_settings(settings, path)
            data = json.loads(path.read_text())
            self.assertEqual(data["schema_version"], 1)
            self.assertEqual(data["orientation"], "yaw_90")
            self.assertEqual(load_settings(path), settings)

    def test_axis_map_round_trip(self) -> None:
        settings = GuiSettings(
            axis_map={"steering": {"wheel": "roll", "throttle": "pitch", "throttle_sign": 1.0}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            save_settings(settings, path)
            loaded = load_settings(path)
            assert loaded is not None
            self.assertEqual(loaded.axis_map["steering"]["wheel"], "roll")
            self.assertEqual(loaded.axis_map["steering"]["throttle"], "pitch")

    def test_legacy_mouse_rate_migrates_to_independent_xy(self) -> None:
        legacy = {
            "schema_version": 1,
            "profile": "mouse",
            "thresholds": {"mouse": {"deadzone_deg": 3.0, "mouse_px_per_sec": 1200.0}},
        }
        parsed = parse_settings(legacy)
        mouse = parsed.thresholds["mouse"]
        self.assertEqual(mouse["mouse_px_per_sec"], 1200.0)
        self.assertEqual(mouse["mouse_x_px_per_sec"], 1200.0)
        self.assertEqual(mouse["mouse_y_px_per_sec"], 1200.0)

    def test_legacy_steering_without_brake_fields_uses_defaults(self) -> None:
        parsed = parse_settings(
            {
                "schema_version": 1,
                "profile": "steering",
                "thresholds": {"steering": {"deadzone_deg": 8.0, "full_scale_deg": 90.0}},
            }
        )
        # Overrides keep only stored keys; session/profile defaults fill brake_*.
        self.assertEqual(parsed.thresholds["steering"]["deadzone_deg"], 8.0)
        self.assertNotIn("brake_full_scale_deg", parsed.thresholds["steering"])

    def test_missing_file_is_none_and_bad_json_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.json"
            self.assertIsNone(load_settings(path))
            path.write_text("{nope")
            with self.assertRaises(SettingsError):
                load_settings(path)

    def test_rejects_unknown_and_invalid_fields(self) -> None:
        base = {"schema_version": 1, "profile": "steering"}
        cases = [
            {**base, "live": True},
            {**base, "schema_version": 2},
            {**base, "profile": "flight"},
            {**base, "orientation": "diagonal"},
            {**base, "invert_roll": "yes"},
            {**base, "thresholds": {"steering": {"gain": 2.0}}},
            {**base, "thresholds": {"joystick": {}}},
            {**base, "thresholds": {"steering": {"deadzone_deg": True}}},
            {**base, "thresholds": {"steering": {"deadzone_deg": float("nan")}}},
            {**base, "thresholds": {"steering": {"deadzone_deg": 90.0}}},
            {**base, "thresholds": {"steering": {"brake_deadzone_deg": 50.0, "brake_full_scale_deg": 40.0}}},
            {**base, "thresholds": {"media": {"click_window_s": float("inf")}}},
            {**base, "thresholds": {"media": {"player_cycle_timeout_s": 0.1}}},
            {**base, "thresholds": {"mouse": {"mouse_y_sign": 2.0}}},
            {**base, "axis_map": {"steering": {"wheel": "gyro_z"}}},
            {**base, "axis_map": {"flight": {"wheel": "yaw"}}},
            [],
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(SettingsError):
                parse_settings(case)


class SessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.factory = _Factory()
        self.session = ControllerSession(output_factory=self.factory)

    def tearDown(self) -> None:
        self.session.shutdown()

    def test_output_requires_stream_and_profile_switch_keeps_connection(self) -> None:
        self.assertIsNotNone(self.session.start_output(live=False))
        _pump(self.session)
        self.assertTrue(_wait(lambda: self.session.snapshot().samples > 20))
        conn_id = self.session._conn_id
        before = self.session.snapshot().samples
        self.assertIsNone(self.session.start_output(live=False))
        self.assertIsNone(self.session.set_profile("mouse"))
        self.assertTrue(_wait(lambda: self.session.snapshot().samples > before + 20))
        snap = self.session.snapshot()
        self.assertEqual(snap.connection, ConnectionState.STREAMING)
        self.assertEqual(self.session._conn_id, conn_id)
        self.assertEqual(snap.output_mode, OutputMode.DRY_RUN)
        self.assertEqual(snap.profile.mode, "mouse")
        _live, output = self.factory.created[-1]
        self.assertTrue(any(r.neutralization_reason == "profile change" for r in output.receipts))

    def test_disconnect_neutralizes_and_reconnect_stays_off(self) -> None:
        self.session.set_profile("mouse")
        _pump(self.session)
        self.assertTrue(_wait(lambda: self.session.snapshot().samples > 5))
        self.assertIsNone(self.session.start_output(live=True))
        _live, output = self.factory.created[-1]
        self.assertTrue(_live)
        self.assertEqual(self.session.snapshot().output_mode, OutputMode.LIVE)
        self.session.disconnect()
        snap = self.session.snapshot()
        self.assertEqual(snap.connection, ConnectionState.DISCONNECTED)
        self.assertEqual(snap.output_mode, OutputMode.OFF)
        self.assertEqual(output.held_buttons, set())
        self.assertTrue(output.closed)
        _pump(self.session)
        self.assertTrue(_wait(lambda: self.session.snapshot().samples > 5))
        self.assertEqual(self.session.snapshot().output_mode, OutputMode.OFF)
        self.assertFalse(self.session._runtime.active)

    def test_live_failure_is_reported_not_raised(self) -> None:
        session = ControllerSession(
            output_factory=_Factory(live_error=PermissionError("/dev/uinput")),
        )
        try:
            _stream(session)
            error = session.start_output(live=True)
            self.assertIn("/dev/uinput", error or "")
            self.assertEqual(session.snapshot().output_mode, OutputMode.OFF)
        finally:
            session.shutdown()

    def test_calibration_rejects_motion_and_keeps_previous_bias(self) -> None:
        # Mouse locks horizontal (identity mount for sensor-frame gyro X).
        self.assertIsNone(self.session.set_profile("mouse"))
        self.assertEqual(self.session.snapshot().orientation, "horizontal")
        self.assertIsNotNone(self.session.begin_calibration())
        conn_id = _stream(self.session)
        self.assertIsNone(self.session.begin_calibration(duration_s=0.2))
        t = _feed(self.session, conn_id, [(131, 0, 0)] * 15, start_seq=1, start_ns=1_000_000_000)
        cal = self.session.snapshot().calibration
        self.assertEqual(cal.state, "accepted")
        self.assertEqual(cal.bias_dps, (1.0, 0.0, 0.0))

        self.assertIsNone(self.session.begin_calibration(duration_s=0.2))
        shaky = [(2000, 0, 0), (-2000, 0, 0)] * 8
        _feed(self.session, conn_id, shaky, start_seq=100, start_ns=t + 20_000_000)
        cal = self.session.snapshot().calibration
        self.assertEqual(cal.state, "rejected")
        self.assertIn("niestabilny", cal.detail)
        self.assertEqual(cal.bias_dps, (1.0, 0.0, 0.0))

    def test_disconnect_aborts_calibration(self) -> None:
        conn_id = _stream(self.session)
        self.session.begin_calibration(duration_s=5.0)
        _feed(self.session, conn_id, [(0, 0, 0)] * 3, start_seq=1, start_ns=1_000_000_000)
        self.session.disconnect()
        cal = self.session.snapshot().calibration
        self.assertEqual(cal.state, "rejected")
        self.assertIsNone(cal.bias_dps)

    def test_recenter_does_not_touch_bias(self) -> None:
        self.assertIsNotNone(self.session.recenter())
        conn_id = _stream(self.session)
        _feed(self.session, conn_id, [(0, 0, 0)] * 3, start_seq=1, start_ns=1_000_000_000)
        self.assertIsNone(self.session.recenter())
        revision = self.session.snapshot().motion
        _feed(self.session, conn_id, [(0, 0, 0)], start_seq=10, start_ns=2_000_000_000)
        motion = self.session.snapshot().motion
        self.assertIsNotNone(revision)
        self.assertIn("origin:", motion.calibration_revision or "")
        self.assertNotIn("bias:", motion.calibration_revision or "")
        self.assertEqual(self.session.snapshot().calibration.state, "idle")

    def test_thresholds_validate_and_apply_without_reopening(self) -> None:
        _stream(self.session)
        self.assertIsNone(self.session.start_output(live=False))
        _live, output = self.factory.created[-1]
        error = self.session.set_threshold("deadzone_deg", 90.0)
        self.assertIn("Nieprawidłowa", error or "")
        self.assertEqual(self.session.thresholds()["deadzone_deg"], 10.0)
        self.assertIsNone(self.session.set_threshold("deadzone_deg", 8.0))
        self.assertEqual(self.session.snapshot().profile.deadzone_deg, 8.0)
        self.assertIs(self.session._runtime.output, output)
        self.assertTrue(output.opened and not output.closed)
        self.assertIsNotNone(self.session.set_threshold("gain", 1.0))

        settings = self.session.current_settings()
        self.assertEqual(settings.thresholds, {"steering": {"deadzone_deg": 8.0}})
        parse_settings(settings.to_json())
        self.session.reset_thresholds()
        self.assertEqual(self.session.thresholds()["deadzone_deg"], 10.0)
        self.assertIsNone(self.session.apply_settings(settings))
        self.assertEqual(self.session.thresholds()["deadzone_deg"], 8.0)

    def test_live_threshold_updates_no_transport_restart_and_reset(self) -> None:
        _pump(self.session)
        self.assertTrue(_wait(lambda: self.session.snapshot().samples > 5))
        conn_id = self.session._conn_id
        transport = self.session.snapshot().transport
        self.assertIsNone(self.session.start_output(live=False))
        before = self.session.snapshot().samples

        self.assertIsNone(
            self.session.set_thresholds(
                {
                    "deadzone_deg": 12.0,
                    "full_scale_deg": 90.0,
                    "brake_deadzone_deg": 15.0,
                    "brake_full_scale_deg": 100.0,
                }
            )
        )
        snap = self.session.snapshot()
        self.assertEqual(self.session._conn_id, conn_id)
        self.assertEqual(snap.transport, transport)
        self.assertEqual(snap.connection, ConnectionState.STREAMING)
        self.assertEqual(snap.profile.brake_full_scale_deg, 100.0)
        self.assertTrue(_wait(lambda: self.session.snapshot().samples > before + 5))

        self.assertIsNone(self.session.set_profile("mouse"))
        self.assertEqual(self.session._conn_id, conn_id)
        self.assertIsNone(
            self.session.set_thresholds(
                {
                    "deadzone_deg": 10.0,
                    "full_scale_deg": 120.0,
                    "mouse_x_px_per_sec": 2000.0,
                    "mouse_y_px_per_sec": 900.0,
                    "mouse_x_sign": -1.0,
                    "mouse_y_sign": 1.0,
                }
            )
        )
        self.assertEqual(self.session.snapshot().profile.mouse_x_px_per_sec, 2000.0)
        self.assertEqual(self.session.snapshot().profile.mouse_x_sign, -1.0)

        self.assertIsNone(self.session.set_profile("media"))
        self.assertIsNone(
            self.session.set_thresholds(
                {
                    "volume_tilt_deg": 60.0,
                    "volume_repeat_s": 0.2,
                    "click_window_s": 0.35,
                    "invert_hold_s": 0.2,
                    "player_cycle_timeout_s": 3.0,
                }
            )
        )
        self.assertEqual(self.session.snapshot().profile.click_window_s, 0.35)
        self.assertEqual(self.session.snapshot().profile.player_cycle_timeout_s, 3.0)
        self.assertIsNone(self.session.reset_thresholds())
        self.assertEqual(self.session.thresholds()["click_window_s"], 0.40)
        # Per-profile reset: steering overrides from earlier remain until that profile resets.
        self.assertIsNone(self.session.set_profile("steering"))
        self.assertEqual(self.session.thresholds()["brake_full_scale_deg"], 100.0)
        self.assertIsNone(self.session.reset_thresholds())
        self.assertEqual(self.session.thresholds()["brake_full_scale_deg"], 40.0)
        self.assertEqual(self.session._conn_id, conn_id)

    def test_inversion_and_stop_keep_center(self) -> None:
        conn_id = _stream(self.session)
        self.session.start_output(live=False)
        self.assertIsNone(self.session.set_inversion(invert_pitch=True, invert_roll=False))
        self.assertEqual(self.session.snapshot().profile.pitch_sign, -1.0)
        _feed(self.session, conn_id, [(0, 0, 0)] * 10, start_seq=1, start_ns=1_000_000_000)
        self.session.stop_output()
        self.assertTrue(self.session._runtime._armed)
        self.assertEqual(self.session.snapshot().output_mode, OutputMode.OFF)

    def test_orientation_change_rearms(self) -> None:
        # Mouse/media/steering lock mounts; only free remount is unused — use
        # steering→mouse switch which force-locks horizontal and re-arms.
        conn_id = _stream(self.session)
        _feed(self.session, conn_id, [(0, 0, 0)] * 12, start_seq=1, start_ns=1_000_000_000)
        self.assertTrue(self.session._runtime._armed)
        self.assertEqual(self.session.snapshot().orientation, "vertical")
        self.assertIsNone(self.session.set_profile("mouse"))
        self.assertEqual(self.session.snapshot().orientation, "horizontal")
        self.assertFalse(self.session._runtime._armed)
        self.assertEqual(self.session.current_settings().orientation, "horizontal")

    def test_media_profile_locks_horizontal(self) -> None:
        # Default profile is steering → vertical mount.
        self.assertEqual(self.session.snapshot().orientation, "vertical")
        self.assertIsNone(self.session.set_profile("media"))
        snap = self.session.snapshot()
        self.assertEqual(snap.profile_name, "media")
        self.assertEqual(snap.orientation, "horizontal")
        msg = self.session.set_orientation("vertical")
        self.assertIsNotNone(msg)
        self.assertEqual(self.session.snapshot().orientation, "horizontal")
        self.assertIsNone(self.session.set_profile("steering"))
        self.assertEqual(self.session.snapshot().orientation, "vertical")
        msg2 = self.session.set_orientation("horizontal")
        self.assertIsNotNone(msg2)
        self.assertEqual(self.session.snapshot().orientation, "vertical")
        self.assertIsNone(self.session.set_profile("media"))
        self.assertEqual(self.session.snapshot().orientation, "horizontal")


class CliGuiArgsTests(unittest.TestCase):
    def test_gui_subcommand_parses(self) -> None:
        from triki_controller.cli.main import build_parser

        args = build_parser().parse_args(["gui", "--transport", "ble", "--connect"])
        self.assertEqual(args.command, "gui")
        self.assertEqual(args.transport, "ble")
        self.assertTrue(args.connect)


if __name__ == "__main__":
    unittest.main()
