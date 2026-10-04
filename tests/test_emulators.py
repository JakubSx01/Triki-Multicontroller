"""Emulator profiles: steering, mouse, media. Scripted poses, not a live CAP001 capture."""

from __future__ import annotations

import unittest
from dataclasses import replace

from triki_controller.core.models import (
    SCHEMA_VERSION,
    MappedState,
    MotionSample,
    PipelineStageStatus,
    QualityFlags,
)
from triki_controller.motion.tilt import TiltMotionProcessor
from triki_controller.output.trace import TraceOutput
from triki_controller.profiles.builtin import profile_by_name, steering_profile, with_overrides
from triki_controller.profiles.devices import DeviceProfileMapper
from triki_controller.runtime.synthetic import make_raw, pose_level, pose_pitch_deg, pose_roll_deg
from triki_controller.runtime.emulator import EmulatorRuntime


def _motion(**kwargs: object) -> MotionSample:
    data: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "raw_session_id": "s",
        "raw_connection_epoch": 1,
        "raw_sample_seq": 1,
        "dt_s": 0.02,
        "accel_m_s2": (0.0, 0.0, -9.8),
        "gyro_rad_s": (0.0, 0.0, 0.0),
        "relative_orientation": None,
        "calibration_revision": None,
        "quality_flags": QualityFlags(not_measured=True),
        "stage_status": PipelineStageStatus.AVAILABLE,
        "button": False,
        "received_monotonic_ns": 1_000_000_000,
        "tilt_pitch_deg": 0.0,
        "tilt_roll_deg": 0.0,
        "tilt_yaw_deg": 90.0,
        "gravity_alignment": 1.0,
    }
    data.update(kwargs)
    return MotionSample(**data)  # type: ignore[arg-type]


class TiltProcessorTests(unittest.TestCase):
    def test_level_then_roll_and_recenter_keeps_raw(self) -> None:
        processor = TiltMotionProcessor()
        level = make_raw(accel=pose_level(), seq=1, t_ns=0)
        before = level.accel_counts
        first = processor.process(level)
        self.assertEqual(level.accel_counts, before)
        self.assertAlmostEqual(first.tilt_roll_deg or 0.0, 0.0, delta=1.0)
        self.assertTrue(first.quality_flags.not_measured)
        self.assertIsNone(first.gravity_alignment)

        rolled = first
        for index in range(25):
            rolled = processor.process(
                make_raw(
                    accel=pose_roll_deg(30),
                    seq=2 + index,
                    t_ns=20_000_000 * (index + 1),
                )
            )
        self.assertAlmostEqual(rolled.tilt_roll_deg or 0.0, 30.0, delta=2.0)
        processor.recenter()
        again = processor.process(
            make_raw(accel=pose_roll_deg(30), seq=40, t_ns=20_000_000 * 40)
        )
        self.assertAlmostEqual(again.tilt_roll_deg or 0.0, 0.0, delta=1.0)
        self.assertGreater(again.gravity_alignment or 0.0, 0.99)
        self.assertIn("origin:", again.calibration_revision or "")

        flipped = processor.process(make_raw(accel=(0, 0, 2048), seq=41, t_ns=20_000_000 * 41))
        later = flipped
        for index in range(5):
            later = processor.process(
                make_raw(accel=(0, 0, 2048), seq=42 + index, t_ns=20_000_000 * (42 + index))
            )
        delta = abs(
            ((later.tilt_roll_deg or 0.0) - (flipped.tilt_roll_deg or 0.0) + 180.0) % 360.0 - 180.0
        )
        self.assertGreater(abs(flipped.tilt_roll_deg or 0.0), 140.0)
        self.assertLess(delta, 5.0)

    def test_gap_does_not_integrate_yaw(self) -> None:
        processor = TiltMotionProcessor()
        processor.process(make_raw(accel=pose_level(), seq=1, t_ns=0, gyro=(0, 0, 13100)))
        later = processor.process(
            make_raw(accel=pose_level(), seq=2, t_ns=1_000_000_000, gyro=(0, 0, 13100))
        )
        self.assertIsNone(later.dt_s)
        self.assertAlmostEqual(later.tilt_yaw_deg or 0.0, 0.0, delta=1.0)
        self.assertTrue(any("gap" in note for note in later.quality_flags.notes))

    def test_gyro_bias_changes_coast_and_not_raw(self) -> None:
        window = [
            make_raw(accel=pose_level(), gyro=(1310, 0, 0), seq=i, t_ns=i)
            for i in range(6)
        ]
        raw_before = window[0].accel_counts

        plain = TiltMotionProcessor()
        plain.process(make_raw(accel=pose_level(), seq=1, t_ns=0))
        last_plain = plain.process(make_raw(accel=pose_level(), seq=2, t_ns=1))
        for i in range(10):
            last_plain = plain.process(
                make_raw(accel=(0, 0, 0), gyro=(1310, 0, 0), seq=10 + i, t_ns=(i + 1) * 50_000_000)
            )

        biased = TiltMotionProcessor()
        result = biased.calibrate(window)
        self.assertTrue(result.accepted)
        self.assertEqual(window[0].accel_counts, raw_before)
        biased.process(make_raw(accel=pose_level(), seq=1, t_ns=0))
        last_biased = biased.process(make_raw(accel=pose_level(), seq=2, t_ns=1))
        for i in range(10):
            last_biased = biased.process(
                make_raw(accel=(0, 0, 0), gyro=(1310, 0, 0), seq=10 + i, t_ns=(i + 1) * 50_000_000)
            )
        self.assertLess(last_plain.tilt_roll_deg or 0.0, -3.0)
        self.assertAlmostEqual(last_biased.tilt_roll_deg or 0.0, 0.0, delta=1.0)

        rejected = biased.calibrate(window[:2])
        self.assertFalse(rejected.accepted)
        noisy = [
            make_raw(
                accel=pose_level(),
                gyro=(0 if i % 2 == 0 else 13100, 0, 0),
                seq=i,
                t_ns=i,
            )
            for i in range(6)
        ]
        self.assertFalse(biased.calibrate(noisy).accepted)


class ProfileMappingTests(unittest.TestCase):
    def test_steering_button_recenters_wheel(self) -> None:
        """Physical button sets current wheel-pot pose as center."""
        from triki_controller.motion.orientation import unmap_counts

        output = TraceOutput()
        # Wheel is roll on the vertical mount; button zeros that origin.
        runtime = EmulatorRuntime(
            profile=steering_profile(), output=output, orientation="vertical"
        )
        runtime.activate(live=False)
        seq = 0
        t = 0
        level = unmap_counts(pose_level(), "vertical")
        rolled = unmap_counts(pose_roll_deg(-55), "vertical")

        def feed(
            *,
            accel: tuple[int, int, int] = level,
            button: bool = False,
        ) -> object:
            nonlocal seq, t
            seq += 1
            t += 20_000_000
            return runtime.feed(make_raw(accel=accel, seq=seq, t_ns=t, button=button))

        for _ in range(12):
            feed()
        twisted = None
        for _ in range(40):
            twisted = feed(accel=rolled)
        assert twisted is not None
        self.assertGreater(twisted.mapped.absolute_axes["wheel"], 0.35)
        recentered = feed(accel=rolled, button=True)
        self.assertIn("recenter", recentered.mapped.pulses)
        self.assertAlmostEqual(recentered.mapped.absolute_axes["wheel"], 0.0, places=2)
        held = feed(accel=rolled, button=True)
        self.assertNotIn("recenter", held.mapped.pulses)
        self.assertAlmostEqual(held.mapped.absolute_axes["wheel"], 0.0, delta=0.15)
        runtime.deactivate("stop")

    def test_steering_wheel_pot_and_pedals_axes(self) -> None:
        mapper = DeviceProfileMapper()
        profile = steering_profile()
        neutral = mapper.map(_motion(tilt_yaw_deg=0.0, tilt_pitch_deg=0.0), profile)
        self.assertEqual(neutral.absolute_axes["wheel"], 0.0)
        self.assertEqual(neutral.absolute_axes["throttle"], 0.0)
        self.assertEqual(neutral.absolute_axes["brake"], 0.0)

        # Yaw must not steer. The wheel is roll (wheel_sign −1, so −roll is +wheel).
        yaw_only = mapper.map(_motion(tilt_yaw_deg=-55, tilt_roll_deg=0, tilt_pitch_deg=0), profile)
        self.assertAlmostEqual(yaw_only.absolute_axes["wheel"], 0.0, places=3)
        self.assertEqual(yaw_only.absolute_axes["throttle"], 0.0)
        right = mapper.map(_motion(tilt_roll_deg=-55, tilt_pitch_deg=0), profile)
        self.assertGreater(right.absolute_axes["wheel"], 0.45)
        self.assertAlmostEqual(right.absolute_axes["wheel_deg"], 55.0, places=1)
        nudge = mapper.map(_motion(tilt_roll_deg=-12, tilt_pitch_deg=0), profile)
        self.assertLess(nudge.absolute_axes["wheel"], 0.12)
        # Forward tip is negative pitch → throttle. Yaw does not steer.
        gas = mapper.map(_motion(tilt_pitch_deg=-40, tilt_yaw_deg=40, tilt_roll_deg=0), profile)
        self.assertGreater(gas.absolute_axes["throttle"], 0.2)
        self.assertEqual(gas.absolute_axes["brake"], 0.0)
        self.assertEqual(gas.absolute_axes["wheel"], 0.0)
        brake = mapper.map(_motion(tilt_pitch_deg=40, tilt_yaw_deg=0), profile)
        self.assertGreater(brake.absolute_axes["brake"], 0.35)
        self.assertEqual(brake.absolute_axes["throttle"], 0.0)

        mapped = DeviceProfileMapper()
        mapped.set_axis_map({
            "steering": {
                "wheel": "roll",
                "wheel_sign": 1.0,
                "throttle": "pitch",
                "throttle_sign": 1.0,
                "brake": "off",
            },
        })
        custom = mapped.map(_motion(tilt_roll_deg=90, tilt_yaw_deg=0, tilt_pitch_deg=-40), profile)
        self.assertAlmostEqual(custom.absolute_axes["wheel"], 1.0, places=2)
        self.assertGreater(custom.absolute_axes["throttle"], 0.2)
        self.assertEqual(custom.absolute_axes["brake"], 0.0)

        flipped = mapper.map(
            _motion(tilt_pitch_deg=-40, tilt_yaw_deg=0),
            profile_by_name("steering", invert_pitch=True),
        )
        self.assertGreater(flipped.absolute_axes["brake"], 0.35)
        self.assertEqual(flipped.absolute_axes["throttle"], 0.0)

    def test_axis_map_can_steer_from_roll_and_disable_brake(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_axis_map(
            {"steering": {"wheel": "roll", "wheel_sign": 1.0, "throttle": "off", "brake": "off"}}
        )
        profile = steering_profile()
        steered = mapper.map(
            _motion(tilt_roll_deg=55, tilt_yaw_deg=-55, tilt_pitch_deg=70),
            profile,
        )
        self.assertGreater(steered.absolute_axes["wheel"], 0.45)
        self.assertAlmostEqual(steered.absolute_axes["wheel_deg"], 55.0, places=1)
        self.assertEqual(steered.absolute_axes["brake"], 0.0)
        self.assertEqual(steered.absolute_axes["throttle"], 0.0)
        yaw_only = mapper.map(
            _motion(tilt_roll_deg=0, tilt_yaw_deg=-55, tilt_pitch_deg=0),
            profile,
        )
        self.assertAlmostEqual(yaw_only.absolute_axes["wheel"], 0.0, places=3)

    def test_steering_defaults_split_pitch_into_throttle_and_brake(self) -> None:
        mapper = DeviceProfileMapper()
        profile = steering_profile()
        self.assertEqual(profile.brake_full_scale_deg, 40.0)
        self.assertEqual(profile.throttle_full_scale_deg, 40.0)
        self.assertEqual(profile.brake_deadzone_deg, 8.0)
        self.assertEqual(profile.throttle_deadzone_deg, 8.0)
        forward = mapper.map(_motion(tilt_pitch_deg=-35), profile)
        self.assertGreater(forward.absolute_axes["throttle"], 0.2)
        self.assertEqual(forward.absolute_axes["brake"], 0.0)
        back = mapper.map(_motion(tilt_pitch_deg=35), profile)
        self.assertGreater(back.absolute_axes["brake"], 0.2)
        self.assertEqual(back.absolute_axes["throttle"], 0.0)
        from triki_controller.profiles.axis_map import DEFAULT_AXIS_MAP

        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["wheel"], "roll")
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["wheel_sign"], -1.0)
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["throttle"], "pitch")
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["brake"], "pitch")
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["throttle_sign"], 1.0)
        self.assertEqual(DEFAULT_AXIS_MAP["steering"]["brake_sign"], 1.0)

    def test_mouse_air_gyro_and_click_pulses(self) -> None:
        import math

        mapper = DeviceProfileMapper()
        profile = profile_by_name("mouse")
        gyro = mapper.map(
            _motion(gyro_rad_s=(0.0, math.radians(-60.0), math.radians(60.0)), tilt_roll_deg=0.0, tilt_pitch_deg=0.0),
            profile,
        )
        self.assertEqual(gyro.relative_deltas["pointer_x"], 0.0)
        self.assertEqual(gyro.relative_deltas["pointer_y"], 0.0)
        # Device X (pitch / accel X) is left-right. Device Y (roll / accel Y) is front-back.
        right = mapper.map(_motion(tilt_pitch_deg=30.0, tilt_roll_deg=0.0), profile)
        self.assertNotEqual(right.relative_deltas["pointer_x"], 0.0)
        self.assertEqual(right.relative_deltas["pointer_y"], 0.0)
        forward = mapper.map(_motion(tilt_roll_deg=30.0, tilt_pitch_deg=0.0), profile)
        self.assertNotEqual(forward.relative_deltas["pointer_y"], 0.0)
        self.assertEqual(forward.relative_deltas["pointer_x"], 0.0)
        from triki_controller.profiles.axis_map import DEFAULT_AXIS_MAP

        self.assertEqual(DEFAULT_AXIS_MAP["mouse"]["x"], "pitch")
        self.assertEqual(DEFAULT_AXIS_MAP["mouse"]["y"], "roll")
        self.assertEqual(profile.mouse_x_sign, 1.0)
        self.assertEqual(right.held_buttons, ())

        pulses: list[str] = []

        def step(t_ms: int, **kwargs: object) -> MappedState:
            state = mapper.map(
                _motion(received_monotonic_ns=t_ms * 1_000_000, **kwargs),
                profile,
            )
            pulses.extend(state.pulses)
            return state

        step(0, button=True)
        step(40, button=False)
        step(500, button=False)
        self.assertEqual(pulses, ["mouse_left"])

        pulses.clear()
        mapper.reset()
        step(1000, button=True)
        step(1040, button=False)
        step(1100, button=True)
        step(1140, button=False)
        step(1600, button=False)
        self.assertEqual(pulses, ["mouse_right"])

    def test_mouse_reported_channel_transform_and_inversions(self) -> None:
        mapper = DeviceProfileMapper()
        profile = profile_by_name("mouse", invert_roll=True)
        state = mapper.map(_motion(tilt_roll_deg=30.0, tilt_pitch_deg=0.0), profile)
        plain = mapper.map(_motion(tilt_roll_deg=30.0, tilt_pitch_deg=0.0), profile_by_name("mouse"))
        self.assertAlmostEqual(state.relative_deltas["pointer_y"], -plain.relative_deltas["pointer_y"], places=6)
        self.assertEqual(state.relative_deltas["pointer_x"], 0.0)
        for dt in (None, 0, -0.01, 0.21):
            held = mapper.map(_motion(tilt_roll_deg=30.0, tilt_pitch_deg=30.0, dt_s=dt), profile_by_name("mouse"))
            self.assertEqual(held.relative_deltas, {"pointer_x": 0.0, "pointer_y": 0.0})

    def test_plane_holds_tilt_like_a_stick(self) -> None:
        import math

        mapper = DeviceProfileMapper()
        profile = profile_by_name("plane")
        spinning = mapper.map(
            _motion(
                gyro_rad_s=(0.0, math.radians(80.0), 0.0),
                tilt_roll_deg=0.0,
                tilt_pitch_deg=0.0,
            ),
            profile,
        )
        self.assertEqual(spinning.absolute_axes["stick_x"], 0.0)
        self.assertEqual(spinning.absolute_axes["stick_y"], 0.0)
        halfway = (45.0 - profile.deadzone_deg) / (profile.full_scale_deg - profile.deadzone_deg)
        left = mapper.map(_motion(tilt_pitch_deg=45.0, tilt_roll_deg=0.0), profile)
        self.assertAlmostEqual(left.absolute_axes["stick_x"], halfway, places=3)
        self.assertEqual(left.absolute_axes["stick_y"], 0.0)
        still = mapper.map(
            _motion(tilt_pitch_deg=45.0, tilt_roll_deg=0.0, gyro_rad_s=(0.0, 0.0, 0.0)),
            profile,
        )
        self.assertAlmostEqual(still.absolute_axes["stick_x"], left.absolute_axes["stick_x"], places=6)
        forward = mapper.map(_motion(tilt_roll_deg=45.0, tilt_pitch_deg=0.0), profile)
        self.assertAlmostEqual(forward.absolute_axes["stick_y"], halfway, places=3)
        self.assertEqual(forward.absolute_axes["stick_x"], 0.0)
        held = mapper.map(_motion(button=True, tilt_roll_deg=0.0, tilt_pitch_deg=0.0), profile)
        self.assertEqual(held.held_buttons, ("trigger",))
        from triki_controller.output.virtual_pointer import stick_to_screen

        center = stick_to_screen(0.0)
        edge = stick_to_screen(1.0)
        placed = stick_to_screen(left.absolute_axes["stick_x"])
        self.assertAlmostEqual(placed, (center + edge) / 2, delta=400)

    def test_mouse_independent_xy_sensitivity_and_sign(self) -> None:
        import math

        mapper = DeviceProfileMapper()
        base = profile_by_name("mouse")
        pose = dict(tilt_roll_deg=40.0, tilt_pitch_deg=40.0)
        equal = mapper.map(_motion(**pose), base)
        hot_x = mapper.map(
            _motion(**pose),
            with_overrides(base, mouse_x_px_per_sec=2800.0, mouse_y_px_per_sec=700.0),
        )
        inv_y = mapper.map(
            _motion(**pose),
            with_overrides(base, mouse_y_sign=-1.0),
        )
        self.assertGreater(abs(hot_x.relative_deltas["pointer_x"]), abs(equal.relative_deltas["pointer_x"]))
        self.assertLess(abs(hot_x.relative_deltas["pointer_y"]), abs(equal.relative_deltas["pointer_y"]))
        self.assertAlmostEqual(
            inv_y.relative_deltas["pointer_y"],
            -equal.relative_deltas["pointer_y"],
            places=6,
        )
        self.assertAlmostEqual(
            inv_y.relative_deltas["pointer_x"],
            equal.relative_deltas["pointer_x"],
            places=6,
        )

    def test_steering_wheel_range_independent_of_brake(self) -> None:
        mapper = DeviceProfileMapper()
        base = steering_profile()
        # Mid-range wheel angle: smaller full_scale saturates harder.
        wide = mapper.map(
            _motion(tilt_roll_deg=-40, tilt_pitch_deg=0),
            with_overrides(base, full_scale_deg=120.0, deadzone_deg=5.0),
        )
        tight = mapper.map(
            _motion(tilt_roll_deg=-40, tilt_pitch_deg=0),
            with_overrides(base, full_scale_deg=45.0, deadzone_deg=5.0),
        )
        self.assertGreater(tight.absolute_axes["wheel"], wide.absolute_axes["wheel"])
        self.assertEqual(tight.absolute_axes["brake"], 0.0)
        self.assertEqual(wide.absolute_axes["throttle"], 0.0)

        # Changing wheel range must not change brake for the same tip-back.
        brake_ref = mapper.map(
            _motion(tilt_pitch_deg=40, tilt_yaw_deg=0),
            with_overrides(base, full_scale_deg=45.0),
        )
        brake_wide_wheel = mapper.map(
            _motion(tilt_pitch_deg=40, tilt_yaw_deg=0),
            with_overrides(base, full_scale_deg=150.0),
        )
        self.assertAlmostEqual(
            brake_ref.absolute_axes["brake"],
            brake_wide_wheel.absolute_axes["brake"],
            places=6,
        )
        self.assertGreater(brake_ref.absolute_axes["brake"], 0.2)

        soft_brake = mapper.map(
            _motion(tilt_pitch_deg=40, tilt_yaw_deg=0),
            with_overrides(base, brake_full_scale_deg=160.0, brake_deadzone_deg=10.0),
        )
        hard_brake = mapper.map(
            _motion(tilt_pitch_deg=40, tilt_yaw_deg=0),
            with_overrides(base, brake_full_scale_deg=80.0, brake_deadzone_deg=10.0),
        )
        self.assertGreater(hard_brake.absolute_axes["brake"], soft_brake.absolute_axes["brake"])
        # Wheel unchanged when only brake params move.
        wheel_only = mapper.map(
            _motion(tilt_roll_deg=-40, tilt_pitch_deg=0),
            with_overrides(base, brake_full_scale_deg=80.0),
        )
        wheel_base = mapper.map(_motion(tilt_roll_deg=-40, tilt_pitch_deg=0), base)
        self.assertAlmostEqual(wheel_only.absolute_axes["wheel"], wheel_base.absolute_axes["wheel"], places=6)
        soft_gas = mapper.map(
            _motion(tilt_pitch_deg=-30, tilt_yaw_deg=0),
            with_overrides(base, throttle_full_scale_deg=140.0),
        )
        hard_gas = mapper.map(
            _motion(tilt_pitch_deg=-30, tilt_yaw_deg=0),
            with_overrides(base, throttle_full_scale_deg=40.0),
        )
        self.assertGreater(hard_gas.absolute_axes["throttle"], soft_gas.absolute_axes["throttle"])
        self.assertEqual(hard_gas.absolute_axes["brake"], 0.0)
        brake_untouched = mapper.map(
            _motion(tilt_pitch_deg=40, tilt_yaw_deg=0),
            with_overrides(base, throttle_full_scale_deg=140.0, throttle_deadzone_deg=20.0),
        )
        self.assertAlmostEqual(
            brake_untouched.absolute_axes["brake"],
            brake_ref.absolute_axes["brake"],
            places=6,
        )

    def test_profile_rejects_nan_inf_bool_and_bad_deps(self) -> None:
        base = steering_profile()
        cases = [
            {"deadzone_deg": float("nan")},
            {"full_scale_deg": float("inf")},
            {"brake_deadzone_deg": True},  # type: ignore[dict-item]
            {"mouse_x_px_per_sec": -1.0},
            {"deadzone_deg": 80.0},  # above safe limit
            {"deadzone_deg": 50.0, "full_scale_deg": 40.0},  # deadzone >= full_scale
            {"brake_deadzone_deg": 40.0, "brake_full_scale_deg": 20.0},
            {"mouse_x_sign": 0.0},
            {"click_window_s": 0.0},
            {"invert_hold_s": 5.0},
            {"player_cycle_timeout_s": 0.1},
        ]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                with_overrides(base, **changes)  # type: ignore[arg-type]

    def test_media_clicks_volume_and_mute(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = with_overrides(
            profile_by_name("media"), full_scale_deg=40.0, deadzone_deg=2.0
        )
        pulses: list[str] = []
        volumes: list[float] = []

        def step(t_ms: int, **kwargs: object) -> MappedState:
            state = mapper.map(
                _motion(received_monotonic_ns=t_ms * 1_000_000, **kwargs),
                profile,
            )
            pulses.extend(state.pulses)
            if "player_volume" in state.absolute_axes:
                volumes.append(state.absolute_axes["player_volume"])
            return state

        # Static roll must not move volume (yaw deltas only).
        home = step(0, tilt_yaw_deg=0.0, tilt_roll_deg=0.0)
        self.assertAlmostEqual(home.absolute_axes["player_volume"], 0.5, places=3)
        lean = step(50, tilt_yaw_deg=0.0, tilt_roll_deg=30.0)
        self.assertAlmostEqual(lean.absolute_axes["player_volume"], 0.5, places=3)
        self.assertEqual(pulses, [])

        # Endless pot: twist right → louder; stay / twist further past 100% stays;
        # twist left from the ceiling reacts immediately (no unwind).
        right = step(100, tilt_yaw_deg=40.0)
        self.assertGreater(right.absolute_axes["player_volume"], 0.9)
        held = step(150, tilt_yaw_deg=40.0)
        self.assertAlmostEqual(
            held.absolute_axes["player_volume"],
            right.absolute_axes["player_volume"],
            places=3,
        )
        past = step(200, tilt_yaw_deg=80.0)
        self.assertAlmostEqual(past.absolute_axes["player_volume"], 1.0, places=3)
        nudge_left = step(250, tilt_yaw_deg=70.0)
        self.assertLess(nudge_left.absolute_axes["player_volume"], 1.0)
        step(270, tilt_yaw_deg=30.0)
        step(285, tilt_yaw_deg=-10.0)
        left = step(300, tilt_yaw_deg=-40.0)
        self.assertLess(left.absolute_axes["player_volume"], 0.2)
        pulses.clear()

        step(1000, button=True, tilt_yaw_deg=12.0)
        step(1050, button=False, tilt_yaw_deg=12.0)
        step(1500, button=False, tilt_yaw_deg=12.0)
        self.assertEqual(pulses, ["play_pause"])

        pulses.clear()
        mapper.reset()
        mapper.set_media_baseline(0.5)
        step(2000, button=True, tilt_yaw_deg=0.0)
        step(2050, button=False, tilt_yaw_deg=0.0)
        step(2100, button=True, tilt_yaw_deg=0.0)
        step(2150, button=False, tilt_yaw_deg=0.0)
        step(2600, button=False, tilt_yaw_deg=0.0)
        self.assertEqual(pulses, ["next_track"])

        pulses.clear()
        mapper.reset()
        mapper.set_media_baseline(0.5)
        step(3000, button=True, tilt_yaw_deg=0.0)
        step(3050, button=False, tilt_yaw_deg=0.0)
        step(3100, button=True, tilt_yaw_deg=0.0)
        step(3150, button=False, tilt_yaw_deg=0.0)
        step(3200, button=True, tilt_yaw_deg=0.0)
        step(3250, button=False, tilt_yaw_deg=0.0)
        step(3700, button=False, tilt_yaw_deg=0.0)
        self.assertEqual(pulses, ["previous_track"])

        pulses.clear()
        mapper.reset()
        mapper.set_media_baseline(0.5)
        step(4000, button=True, tilt_yaw_deg=0.0)
        step(4050, button=False, tilt_yaw_deg=0.0)
        self.assertEqual(mapper.take_pending_click(), "play_pause")

        pulses.clear()
        mapper.reset()
        mapper.set_media_baseline(0.5)
        for index in range(5):
            step(5000 + index * 40, gravity_alignment=-1.0, tilt_roll_deg=180, tilt_yaw_deg=0.0)
        self.assertEqual(pulses, ["mute"])
        for index in range(5):
            step(5300 + index * 40, gravity_alignment=1.0, tilt_roll_deg=0, tilt_yaw_deg=0.0)
        self.assertEqual(pulses, ["mute", "mute"])

    def test_media_invert_twist_controls_system_volume(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.4)
        profile = profile_by_name("media")
        pulses: list[str] = []
        entered = None
        for index in range(5):
            entered = mapper.map(
                _motion(
                    received_monotonic_ns=(5_000 + index * 40) * 1_000_000,
                    gravity_alignment=-1.0,
                    tilt_yaw_deg=10.0,
                ),
                profile,
            )
            pulses.extend(entered.pulses)
        self.assertEqual(pulses, ["mute"])
        assert entered is not None
        self.assertNotIn("player_volume", entered.absolute_axes)
        self.assertAlmostEqual(entered.absolute_axes["system_volume"], 0.0)
        twisted = mapper.map(
            _motion(
                received_monotonic_ns=5_400_000_000,
                gravity_alignment=-1.0,
                tilt_yaw_deg=26.0,
            ),
            profile,
        )
        self.assertEqual(twisted.pulses, ())
        self.assertNotIn("player_volume", twisted.absolute_axes)
        self.assertAlmostEqual(twisted.absolute_axes["system_volume"], -16.0 / 40.0, places=3)
        back: list[str] = []
        restored = None
        for index in range(5):
            restored = mapper.map(
                _motion(
                    received_monotonic_ns=(6_000 + index * 40) * 1_000_000,
                    gravity_alignment=1.0,
                    tilt_yaw_deg=26.0,
                ),
                profile,
            )
            back.extend(restored.pulses)
        self.assertEqual(back, ["mute"])
        assert restored is not None
        self.assertNotIn("system_volume", restored.absolute_axes)
        self.assertAlmostEqual(restored.absolute_axes["player_volume"], 0.4, places=3)

    def test_media_volume_ignores_rotation_until_level(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = profile_by_name("media")
        mapper.map(
            _motion(received_monotonic_ns=1_000_000_000, gravity_alignment=1.0, tilt_yaw_deg=0.0),
            profile,
        )
        tilted = mapper.map(
            _motion(received_monotonic_ns=1_020_000_000, gravity_alignment=0.2, tilt_yaw_deg=90.0),
            profile,
        )
        self.assertAlmostEqual(tilted.absolute_axes["player_volume"], 0.5, places=3)
        spike = mapper.map(
            _motion(received_monotonic_ns=1_040_000_000, gravity_alignment=1.0, tilt_yaw_deg=180.0),
            profile,
        )
        self.assertAlmostEqual(spike.absolute_axes["player_volume"], 0.5, places=3)
        twisted = mapper.map(
            _motion(received_monotonic_ns=1_060_000_000, gravity_alignment=1.0, tilt_yaw_deg=164.0),
            profile,
        )
        self.assertLess(twisted.absolute_axes["player_volume"], 0.5)

        pulses: list[str] = []
        for index in range(5):
            state = mapper.map(
                _motion(
                    received_monotonic_ns=(2_000 + index * 40) * 1_000_000,
                    gravity_alignment=-1.0,
                    tilt_yaw_deg=10.0,
                ),
                profile,
            )
            pulses.extend(state.pulses)
        self.assertEqual(pulses, ["mute"])
        edge = mapper.map(
            _motion(
                received_monotonic_ns=2_400_000_000,
                gravity_alignment=-0.4,
                tilt_yaw_deg=120.0,
            ),
            profile,
        )
        self.assertAlmostEqual(edge.absolute_axes["system_volume"], 0.0, places=3)
        settled = mapper.map(
            _motion(
                received_monotonic_ns=2_500_000_000,
                gravity_alignment=-1.0,
                tilt_yaw_deg=120.0,
            ),
            profile,
        )
        self.assertAlmostEqual(settled.absolute_axes["system_volume"], 0.0, places=3)
        turned = mapper.map(
            _motion(
                received_monotonic_ns=2_600_000_000,
                gravity_alignment=-1.0,
                tilt_yaw_deg=104.0,
            ),
            profile,
        )
        self.assertGreater(turned.absolute_axes["system_volume"], 0.1)

    def test_media_shake_emits_cycle_player_once(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = profile_by_name("media")
        # Gyro X/Y shake. Accel stays at 1 g — magnitude must not be required.
        shake_gyro = (4.0, 3.0, 0.0)
        pulses: list[str] = []
        for index in range(6):
            state = mapper.map(
                _motion(
                    received_monotonic_ns=(100 + index) * 1_000_000,
                    accel_m_s2=(0.0, 0.0, -9.8),
                    gyro_rad_s=shake_gyro,
                    tilt_yaw_deg=0.0,
                ),
                profile,
            )
            pulses.extend(state.pulses)
        self.assertEqual(pulses.count("cycle_player"), 1)
        quiet = mapper.map(
            _motion(
                received_monotonic_ns=900_000_000,
                accel_m_s2=(0.0, 0.0, -9.8),
                gyro_rad_s=(0.0, 0.0, 0.0),
                tilt_yaw_deg=0.0,
            ),
            profile,
        )
        self.assertEqual(quiet.pulses, ())

    def test_media_continuous_shake_cycles_player_once(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = profile_by_name("media")
        pulses: list[str] = []
        for index in range(80):
            state = mapper.map(
                _motion(
                    received_monotonic_ns=index * 20_000_000,
                    accel_m_s2=(0.0, 0.0, -9.8),
                    gyro_rad_s=(4.0, 0.0, 0.0),
                    tilt_yaw_deg=0.0,
                ),
                profile,
            )
            pulses.extend(state.pulses)
        self.assertEqual(pulses.count("cycle_player"), 1)

    def test_media_shake_timeout_blocks_until_quiet_and_lockout(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = with_overrides(profile_by_name("media"), player_cycle_timeout_s=2.0)
        rest = (0.0, 0.0, 0.0)
        shake = (0.0, 4.0, 0.0)
        pulses: list[str] = []

        def burst(t0_ns: int) -> None:
            for index in range(6):
                state = mapper.map(
                    _motion(
                        received_monotonic_ns=t0_ns + index * 20_000_000,
                        gyro_rad_s=shake,
                        tilt_yaw_deg=0.0,
                    ),
                    profile,
                )
                pulses.extend(state.pulses)

        burst(0)
        self.assertEqual(pulses.count("cycle_player"), 1)
        mapper.map(_motion(received_monotonic_ns=200_000_000, gyro_rad_s=rest, tilt_yaw_deg=0.0), profile)
        burst(500_000_000)  # 0.5 s — still inside 2 s lockout
        self.assertEqual(pulses.count("cycle_player"), 1)
        mapper.map(_motion(received_monotonic_ns=2_100_000_000, gyro_rad_s=rest, tilt_yaw_deg=0.0), profile)
        burst(2_200_000_000)
        self.assertEqual(pulses.count("cycle_player"), 2)

    def test_media_shake_short_timeout_allows_second_cycle(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = with_overrides(profile_by_name("media"), player_cycle_timeout_s=0.30)
        rest = (0.0, 0.0, 0.0)
        shake = (4.0, 4.0, 0.0)
        pulses: list[str] = []
        for index in range(6):
            pulses.extend(
                mapper.map(
                    _motion(
                        received_monotonic_ns=index * 20_000_000,
                        gyro_rad_s=shake,
                        tilt_yaw_deg=0.0,
                    ),
                    profile,
                ).pulses
            )
        mapper.map(_motion(received_monotonic_ns=200_000_000, gyro_rad_s=rest, tilt_yaw_deg=0.0), profile)
        for index in range(6):
            pulses.extend(
                mapper.map(
                    _motion(
                        received_monotonic_ns=400_000_000 + index * 20_000_000,
                        gyro_rad_s=shake,
                        tilt_yaw_deg=0.0,
                    ),
                    profile,
                ).pulses
            )
        self.assertEqual(pulses.count("cycle_player"), 2)

    def test_media_volume_twist_does_not_cycle_player(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = profile_by_name("media")
        pulses: list[str] = []
        yaw = 0.0
        high_gyro = (0.0, 0.0, 8.0)  # ~458 dps yaw — volume knob, still ~1 g
        for index in range(8):
            yaw += 12.0
            state = mapper.map(
                _motion(
                    received_monotonic_ns=(100 + index) * 1_000_000,
                    accel_m_s2=(0.0, 0.0, -9.8),
                    gyro_rad_s=high_gyro,
                    tilt_yaw_deg=yaw,
                ),
                profile,
            )
            pulses.extend(state.pulses)
        self.assertNotIn("cycle_player", pulses)

    def test_media_accel_jolt_does_not_cycle_player(self) -> None:
        mapper = DeviceProfileMapper()
        mapper.set_media_baseline(0.5)
        profile = profile_by_name("media")
        pulses: list[str] = []
        for index in range(8):
            pulses.extend(
                mapper.map(
                    _motion(
                        received_monotonic_ns=(100 + index) * 1_000_000,
                        accel_m_s2=(12.0, -8.0, 4.0),
                        gyro_rad_s=(0.0, 0.0, 0.0),
                        tilt_yaw_deg=0.0,
                    ),
                    profile,
                ).pulses
            )
        self.assertNotIn("cycle_player", pulses)

    def test_bad_profile_rejected(self) -> None:
        profile = replace(steering_profile(), mode="flight")
        with self.assertRaises(ValueError):
            profile.validated()


def _burst(
    accel: tuple[int, int, int],
    count: int,
    *,
    start: int,
    button: bool = False,
    gyro: tuple[int, int, int] = (0, 0, 0),
) -> list:
    return [
        make_raw(
            accel=accel,
            seq=start + index,
            t_ns=(start + index) * 20_000_000,
            button=button,
            gyro=gyro,
        )
        for index in range(count)
    ]


class EmulatorRuntimeTests(unittest.TestCase):
    def test_steering_axes_then_neutral(self) -> None:
        from triki_controller.motion.orientation import unmap_counts

        output = TraceOutput()
        runtime = EmulatorRuntime(
            profile=profile_by_name("steering"), output=output, orientation="vertical"
        )
        runtime.activate(live=False)
        level = unmap_counts(pose_level(), "vertical")
        rolled = unmap_counts(pose_roll_deg(-55), "vertical")
        gas = unmap_counts(pose_pitch_deg(-55), "vertical")
        brake = unmap_counts(pose_pitch_deg(55), "vertical")
        samples = (
            _burst(level, 8, start=1)
            + _burst(rolled, 20, start=9)
            + _burst(gas, 20, start=29)
            + _burst(brake, 20, start=49)
        )
        peak_wheel = peak_throttle = peak_brake = 0.0
        for sample in samples:
            step = runtime.feed(sample)
            peak_wheel = max(peak_wheel, step.mapped.absolute_axes.get("wheel", 0.0))
            peak_throttle = max(peak_throttle, step.mapped.absolute_axes.get("throttle", 0.0))
            peak_brake = max(peak_brake, step.mapped.absolute_axes.get("brake", 0.0))
        runtime.deactivate("done")
        self.assertGreater(peak_wheel, 0.35)
        self.assertGreater(peak_throttle, 0.2)
        self.assertGreater(peak_brake, 0.2)
        self.assertEqual(output.axes["wheel"], 0.0)
        self.assertEqual(output.held_buttons, set())
        self.assertTrue(any(r.neutralization_reason == "done" for r in output.receipts))

    def test_mouse_moves_and_clicks(self) -> None:
        output = TraceOutput()
        runtime = EmulatorRuntime(profile=profile_by_name("mouse"), output=output)
        runtime.activate(live=False)
        samples = (
            _burst(pose_level(), 8, start=1)
            + _burst(pose_pitch_deg(30), 12, start=9)
            + _burst(pose_roll_deg(30), 12, start=21)
            + _burst(pose_level(), 3, start=33, button=True)
            + _burst(pose_level(), 25, start=36)
            + _burst(pose_level(), 2, start=61, button=True)
            + _burst(pose_level(), 2, start=63)
            + _burst(pose_level(), 2, start=65, button=True)
            + _burst(pose_level(), 25, start=67)
        )
        saw_x = saw_y = False
        pulses: list[str] = []
        for sample in samples:
            step = runtime.feed(sample)
            if abs(step.mapped.relative_deltas.get("pointer_x", 0.0)) > 0:
                saw_x = True
            if abs(step.mapped.relative_deltas.get("pointer_y", 0.0)) > 0:
                saw_y = True
            pulses.extend(step.mapped.pulses)
        runtime.deactivate("disconnect")
        self.assertTrue(saw_x and saw_y)
        self.assertIn("mouse_left", pulses)
        self.assertIn("mouse_right", pulses)
        self.assertEqual(output.held_buttons, set())
        self.assertTrue(any(r.neutralization_reason == "disconnect" for r in output.receipts))

    def test_profile_switch_and_stale_epoch_release(self) -> None:
        output = TraceOutput()
        runtime = EmulatorRuntime(profile=profile_by_name("mouse"), output=output)
        runtime.activate(live=False)
        for sample in _burst(pose_pitch_deg(30), 8, start=1):
            runtime.feed(sample)
        runtime.switch_profile(profile_by_name("steering"))
        self.assertEqual(output.held_buttons, set())
        self.assertEqual(output.axes.get("wheel"), 0.0)
        self.assertTrue(any(r.neutralization_reason == "profile change" for r in output.receipts))

        stale = MappedState(
            schema_version=SCHEMA_VERSION,
            raw_session_id="s",
            raw_connection_epoch=1,
            raw_sample_seq=1,
            profile_id="mouse",
            profile_revision="builtin-1",
            activation_epoch=1,
            held_buttons=("mouse_left",),
            held_keys=(),
            absolute_axes={"wheel": 1.0},
            relative_deltas={"pointer_x": 5.0},
            stage_status=PipelineStageStatus.AVAILABLE,
            pulses=("volume_up",),
        )
        receipt = output.apply(stale)
        self.assertFalse(receipt.applied)
        self.assertNotIn("mouse_left", output.held_buttons)
        runtime.deactivate("stop")


class CliEmulateTests(unittest.TestCase):
    def test_demo_transport_is_rejected(self) -> None:
        from triki_controller.cli.main import build_parser

        with self.assertRaises(SystemExit):
            build_parser().parse_args(["emulate", "--profile", "steering", "--transport", "demo"])
        args = build_parser().parse_args(["emulate", "--profile", "steering"])
        self.assertEqual(args.transport, "ble")

    def test_emulate_reads_gui_settings_axis_map(self) -> None:
        import argparse
        import tempfile
        from pathlib import Path

        from triki_controller.cli.main import _load_emulate_settings
        from triki_controller.gui.settings import GuiSettings, save_settings
        from triki_controller.profiles.builtin import steering_profile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "gui-settings.json"
            save_settings(
                GuiSettings(axis_map={"steering": {"wheel": "roll", "wheel_sign": 1.0}}),
                path,
            )
            args = argparse.Namespace(settings=path, invert_pitch=False, invert_roll=False)
            _profile, axis_map, loaded = _load_emulate_settings(args, steering_profile())
        self.assertEqual(loaded, path)
        self.assertEqual(axis_map["steering"]["wheel"], "roll")
        self.assertEqual(axis_map["steering"]["wheel_sign"], 1.0)
