"""Mounting orientation remaps and media mapping after remap."""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from triki_controller.gui.settings import GuiSettings, load_settings, parse_settings, save_settings
from triki_controller.motion.orientation import (
    ORIENTATION_IDS,
    get_orientation,
    parse_orientation,
    remap_vector,
    unmap_counts,
)
from triki_controller.motion.tilt import TiltMotionProcessor, accel_tilt_deg
from triki_controller.profiles.builtin import profile_by_name, with_overrides
from triki_controller.profiles.devices import DeviceProfileMapper
from triki_controller.runtime.synthetic import counts_from_g, make_raw, pose_level, pose_roll_deg
from triki_controller.runtime.emulator import EmulatorRuntime
from triki_controller.output.trace import TraceOutput

from tests.test_emulators import _motion


def _settle(processor: TiltMotionProcessor, accel: tuple[int, int, int], *, start_seq: int = 1) -> object:
    last = None
    for index in range(40):
        last = processor.process(
            make_raw(accel=accel, seq=start_seq + index, t_ns=20_000_000 * (start_seq + index))
        )
    assert last is not None
    return last


class OrientationRemapTests(unittest.TestCase):
    def test_parse_aliases(self) -> None:
        self.assertEqual(parse_orientation("poziomo"), "horizontal")
        self.assertEqual(parse_orientation("Pionowo"), "vertical")
        self.assertEqual(parse_orientation("90"), "yaw_90")
        with self.assertRaises(ValueError):
            parse_orientation("diagonal")

    def test_same_physical_gravity_yields_expected_tilt(self) -> None:
        """Control-frame level and +30° roll stay correct after each mounting remap."""
        level_g = (0.0, 0.0, -1.0)
        roll30_g = (0.0, math.sin(math.radians(30)), -math.cos(math.radians(30)))

        for oid in ORIENTATION_IDS:
            with self.subTest(orientation=oid):
                # Sensor reading that becomes the control pose after R.
                level_sensor = unmap_counts(counts_from_g(*level_g), oid)
                roll_sensor = unmap_counts(
                    counts_from_g(roll30_g[0], roll30_g[1], roll30_g[2]), oid
                )
                # Remapped gravity alone matches accel_tilt_deg expectation.
                remapped = remap_vector(
                    tuple(c / 2048.0 for c in roll_sensor), oid  # type: ignore[arg-type]
                )
                tilt = accel_tilt_deg(*remapped)
                self.assertIsNotNone(tilt)
                assert tilt is not None
                self.assertAlmostEqual(tilt[1], 30.0, delta=0.5)

                processor = TiltMotionProcessor(orientation=oid)
                level = _settle(processor, level_sensor)
                self.assertAlmostEqual(level.tilt_pitch_deg or 0.0, 0.0, delta=1.5)
                self.assertAlmostEqual(level.tilt_roll_deg or 0.0, 0.0, delta=1.5)
                processor.recenter()
                rolled = _settle(processor, roll_sensor, start_seq=20)
                self.assertAlmostEqual(rolled.tilt_roll_deg or 0.0, 30.0, delta=2.0)
                self.assertAlmostEqual(rolled.tilt_pitch_deg or 0.0, 0.0, delta=2.0)

    def test_vertical_rest_is_level_only_after_remap(self) -> None:
        # Measured steering rest: gravity on sensor −Y, X and Z near zero.
        tip_up = counts_from_g(0.0, -1.0, 0.0)
        plain = _settle(TiltMotionProcessor(orientation="horizontal"), tip_up)
        self.assertGreater(abs(plain.tilt_roll_deg or 0.0), 60.0)

        vertical = _settle(TiltMotionProcessor(orientation="vertical"), tip_up)
        self.assertAlmostEqual(vertical.tilt_pitch_deg or 0.0, 0.0, delta=1.5)
        self.assertAlmostEqual(vertical.tilt_roll_deg or 0.0, 0.0, delta=1.5)
        assert vertical.accel_m_s2 is not None
        self.assertAlmostEqual(vertical.accel_m_s2[2], -9.8, delta=0.3)
        self.assertAlmostEqual(vertical.accel_m_s2[1], 0.0, delta=0.3)

    def test_media_potentiometer_after_horizontal_arm(self) -> None:
        """Endless pot raises player_volume after yaw twist from connect home."""
        from triki_controller.runtime.synthetic import gyro_yaw_twist_counts

        output = TraceOutput()
        runtime = EmulatorRuntime(
            profile=with_overrides(
                profile_by_name("media"), full_scale_deg=40.0, deadzone_deg=2.0
            ),
            output=output,
            orientation="horizontal",
        )
        runtime.activate(live=False)
        level = pose_level()
        twist = gyro_yaw_twist_counts(60.0)
        peak = 0.0
        for index in range(12):
            runtime.feed(make_raw(accel=level, seq=index + 1, t_ns=index * 20_000_000))
        for index in range(30):
            step = runtime.feed(
                make_raw(
                    accel=level,
                    gyro=twist,
                    seq=100 + index,
                    t_ns=(100 + index) * 20_000_000,
                )
            )
            peak = max(peak, step.mapped.absolute_axes.get("player_volume", 0.0))
        runtime.deactivate("stop")
        self.assertGreater(peak, 0.55)

    def test_media_mapper_uses_yaw_not_roll(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = with_overrides(
            profile_by_name("media"), full_scale_deg=40.0, deadzone_deg=2.0
        )
        held = mapper.map(_motion(tilt_yaw_deg=0.0, tilt_roll_deg=40.0), profile)
        self.assertEqual(held.pulses, ())
        self.assertAlmostEqual(held.absolute_axes["player_volume"], 0.5, places=3)
        # Seed yaw reference, then twist — roll must not matter.
        mapper.map(_motion(tilt_yaw_deg=0.0, tilt_roll_deg=0.0), profile)
        twisted = mapper.map(_motion(tilt_yaw_deg=40.0, tilt_roll_deg=0.0), profile)
        self.assertEqual(twisted.pulses, ())
        self.assertGreater(twisted.absolute_axes["player_volume"], 0.9)

    def test_settings_round_trip_includes_orientation(self) -> None:
        settings = GuiSettings(
            profile="media",
            orientation="vertical",
            invert_roll=True,
            thresholds={"media": {"volume_tilt_deg": 22.0}},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            save_settings(settings, path)
            loaded = load_settings(path)
            self.assertEqual(loaded, settings)
            raw = parse_settings(
                {
                    "schema_version": 1,
                    "profile": "media",
                    "orientation": "pionowo",
                    "invert_pitch": False,
                    "invert_roll": False,
                    "thresholds": {},
                }
            )
            self.assertEqual(raw.orientation, "vertical")

    def test_legacy_settings_default_orientation(self) -> None:
        parsed = parse_settings({"schema_version": 1, "profile": "steering"})
        self.assertEqual(parsed.orientation, "horizontal")
        self.assertEqual(get_orientation("horizontal").label_pl, "Poziomo")

    def test_cli_orientation_flag(self) -> None:
        from triki_controller.cli.main import build_parser

        media = build_parser().parse_args(
            ["emulate", "--profile", "media", "--orientation", "vertical"]
        )
        self.assertEqual(media.orientation, "vertical")
        self.assertEqual(media.transport, "ble")
        rotated = build_parser().parse_args(
            ["emulate", "--profile", "media", "--rotation", "yaw_90"]
        )
        self.assertEqual(rotated.orientation, "yaw_90")
        with self.assertRaises(SystemExit):
            build_parser().parse_args(["emulate", "--profile", "media", "--transport", "demo"])


if __name__ == "__main__":
    unittest.main()
