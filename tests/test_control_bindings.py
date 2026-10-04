"""Replay-only mapper tests: logical outputs, never hardware events."""
from dataclasses import replace
import pytest

from triki_controller.core.models import MotionSample, PipelineStageStatus, QualityFlags
from triki_controller.profiles.builtin import profile_by_name, with_overrides
from triki_controller.profiles.devices import DeviceProfileMapper


def motion(**changes):
    return replace(MotionSample(1, "replay", 7, 19, .02, None, (0., 0., 0.), None, None,
                                QualityFlags(synthetic=True), PipelineStageStatus.AVAILABLE,
                                False, 1_000_000_000, 0., 0., 0., 1.), **changes)


def test_plane_direction_and_physical_button_overlay_preserves_analog_metadata():
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({"plane": {"left": "key_a", "right": "key_d", "button": "mouse_middle"}})
    profile = with_overrides(profile_by_name("plane"), mouse_x_sign=1.)
    sample = motion(tilt_pitch_deg=-60., button=True)
    expected = DeviceProfileMapper().map(sample, profile)
    state = mapper.map(sample, profile)
    assert state.held_keys == ("key_a",)
    assert state.held_buttons == ("mouse_middle",)
    assert replace(state, held_keys=(), held_buttons=("trigger",)) == expected
    reverse = mapper.map(motion(tilt_pitch_deg=60.), profile)
    assert reverse.held_keys == ("key_d",)
    assert reverse.held_buttons == ()
    assert mapper.map(motion(), profile).held_keys == ()


def clicks(mapper, profile, count):
    for index in range(count):
        start = 1_000_000_000 + index * 60_000_000
        mapper.map(motion(button=True, received_monotonic_ns=start), profile)
        mapper.map(motion(button=False, received_monotonic_ns=start + 20_000_000), profile)
    return mapper.map(motion(received_monotonic_ns=2_000_000_000), profile)


def test_unconfigured_mouse_triple_click_keeps_legacy_single_click_fallback():
    assert clicks(DeviceProfileMapper(), profile_by_name("mouse"), 3).pulses == ("mouse_left",)


@pytest.mark.parametrize("mode", ["steering", "mouse", "plane"])
def test_explicit_click_sources_emit_one_pulse_after_quiet_window(mode):
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({mode: {"click": "key_enter", "double_click": "mouse_middle", "triple_click": "key_space"}})
    profile = profile_by_name(mode)
    assert clicks(mapper, profile, 1).pulses == ("key_enter",)
    mapper.reset()
    assert clicks(mapper, profile, 2).pulses == ("mouse_middle",)
    mapper.reset()
    assert clicks(mapper, profile, 3).pulses == ("key_space",)
    assert mapper.map(motion(received_monotonic_ns=3_000_000_000), profile).pulses == ()


@pytest.mark.parametrize("mode", ["mouse", "plane"])
def test_directional_activation_hysteresis_and_reset(mode):
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({mode: {"right": "key_d"}})
    profile = with_overrides(profile_by_name(mode), deadzone_deg=0., full_scale_deg=100.)
    assert mapper.map(motion(tilt_pitch_deg=19.), profile).held_keys == ()
    assert mapper.map(motion(tilt_pitch_deg=20.), profile).held_keys == ("key_d",)
    assert mapper.map(motion(tilt_pitch_deg=16.), profile).held_keys == ("key_d",)
    assert mapper.map(motion(tilt_pitch_deg=15.), profile).held_keys == ()
    mapper.map(motion(tilt_pitch_deg=30.), profile)
    mapper.reset()
    assert mapper.map(motion(tilt_pitch_deg=16.), profile).held_keys == ()
    assert mapper.map(motion(tilt_pitch_deg=30.), profile).held_keys == ("key_d",)


@pytest.mark.parametrize("mode,changes,expected", [
    ("steering", {"tilt_roll_deg": 90., "tilt_pitch_deg": -40.}, ("key_a", "key_w")),
    ("steering", {"tilt_roll_deg": -90., "tilt_pitch_deg": 40.}, ("key_d", "key_s")),
    ("mouse", {"tilt_pitch_deg": -100., "tilt_roll_deg": -100.}, ("key_a", "key_w")),
    ("mouse", {"tilt_pitch_deg": 100., "tilt_roll_deg": 100.}, ("key_d", "key_s")),
    ("plane", {"tilt_pitch_deg": -90., "tilt_roll_deg": -90.}, ("key_a", "key_w")),
    ("plane", {"tilt_pitch_deg": 90., "tilt_roll_deg": 90.}, ("key_d", "key_s")),
])
def test_all_motion_directions_follow_normalized_profile_axes(mode, changes, expected):
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({mode: {"left": "key_a", "right": "key_d", "forward": "key_w", "backward": "key_s"}})
    assert mapper.map(motion(**changes), profile_by_name(mode)).held_keys == expected


def test_mouse_button_override_suppresses_implicit_clicks_but_allows_explicit_click():
    mapper = DeviceProfileMapper()
    profile = profile_by_name("mouse")
    mapper.set_control_bindings({"mouse": {"button": "mouse_left"}})
    assert mapper.map(motion(button=True), profile).held_buttons == ("mouse_left",)
    assert mapper.map(motion(), profile).held_buttons == ()
    assert clicks(mapper, profile, 1).pulses == ()
    mapper.set_control_bindings({"mouse": {"button": "key_shift", "click": "key_enter"}})
    assert mapper.map(motion(button=True), profile).held_keys == ("key_shift",)
    mapper.reset()
    assert clicks(mapper, profile, 1).pulses == ("key_enter",)
    mapper.set_control_bindings({"mouse": {"button": "off"}})
    assert clicks(mapper, profile, 2).pulses == ()
    mapper.set_control_bindings({"mouse": {"click": "off"}})
    assert clicks(mapper, profile, 1).pulses == ()
    mapper.reset()
    assert clicks(mapper, profile, 2).pulses == ("mouse_right",)


def test_profile_switch_and_unavailable_sample_discard_pending_click_and_hysteresis():
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({"plane": {"right": "key_d", "click": "key_enter"}})
    plane = with_overrides(profile_by_name("plane"), deadzone_deg=0., full_scale_deg=100.)
    mapper.map(motion(button=True, tilt_pitch_deg=30.), plane)
    mapper.map(motion(received_monotonic_ns=1_020_000_000), plane)
    assert mapper.map(motion(), profile_by_name("mouse")).held_keys == ()
    assert mapper.map(motion(tilt_pitch_deg=16., received_monotonic_ns=2_000_000_000), plane).held_keys == ()
    assert mapper.take_pending_click() is None
    mapper.map(motion(button=True, tilt_pitch_deg=30.), plane)
    neutral = mapper.map(motion(stage_status=PipelineStageStatus.UNAVAILABLE), plane)
    assert neutral.held_keys == neutral.held_buttons == neutral.pulses == ()
    assert mapper.map(motion(tilt_pitch_deg=16.), plane).held_keys == ()


def test_axis_overlay_inversion_and_deduplication_apply_to_bindings():
    mapper = DeviceProfileMapper()
    mapper.set_axis_map({"plane": {"x": "roll"}})
    mapper.set_control_bindings({"plane": {"left": "key_a", "button": "key_a"}})
    profile = profile_by_name("plane", invert_roll=True)
    state = mapper.map(motion(tilt_roll_deg=90., button=True), profile)
    assert state.held_keys == ("key_a",)
    mapper.reset()
    assert mapper.map(motion(tilt_roll_deg=90.), profile).held_keys == ("key_a",)


@pytest.mark.parametrize("bindings", [{"media": {}}, {"plane": {"yaw": "key_a"}}, {"mouse": {"button": "bogus"}}, {"mouse": None}])
def test_mapper_rejects_invalid_overlays_without_replacing_valid_configuration(bindings):
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({"plane": {"button": "key_a"}})
    with pytest.raises(ValueError):
        mapper.set_control_bindings(bindings)
    assert mapper.map(motion(button=True), profile_by_name("plane")).held_keys == ("key_a",)


def test_media_disable_only_suppresses_shake_cycling_and_retains_setting_after_reset():
    profile = profile_by_name("media")
    mapper = DeviceProfileMapper()
    def shake():
        return [mapper.map(motion(gyro_rad_s=(5., 0., 0.), received_monotonic_ns=1_000_000_000 + i * 20_000_000), profile) for i in range(6)]
    assert any("cycle_player" in state.pulses for state in shake())
    mapper.set_media_gestures_enabled(False)
    mapper.reset()
    assert all("cycle_player" not in state.pulses for state in shake())
    assert clicks(mapper, profile, 1).pulses == ("play_pause",)
    mapper.reset()
    assert clicks(mapper, profile, 2).pulses == ("next_track",)
    mapper.reset()
    assert clicks(mapper, profile, 3).pulses == ("previous_track",)
    mapper.reset()
    mapper.set_media_baseline(.3)
    assert mapper.map(motion(), profile).absolute_axes["player_volume"] == .3
    assert mapper.map(motion(tilt_yaw_deg=20.), profile).absolute_axes["player_volume"] == .8
    mapper.map(motion(gravity_alignment=-1., received_monotonic_ns=3_000_000_000), profile)
    flipped = mapper.map(motion(gravity_alignment=-1., received_monotonic_ns=3_200_000_000), profile)
    assert flipped.pulses == ("mute",)
    assert "system_volume" in flipped.absolute_axes
    mapper.set_media_gestures_enabled(True)
    mapper.reset()
    assert any("cycle_player" in state.pulses for state in shake())


@pytest.mark.parametrize("action,expected_buttons,expected_keys", [
    ("default", ("trigger",), ()), ("off", (), ()),
    ("mouse_right", ("mouse_right",), ()), ("key_9", (), ("key_9",)),
])
def test_plane_button_default_off_and_chosen_action_release(action, expected_buttons, expected_keys):
    mapper = DeviceProfileMapper()
    mapper.set_control_bindings({"plane": {"button": action}})
    profile = profile_by_name("plane")
    held = mapper.map(motion(button=True), profile)
    assert held.held_buttons == expected_buttons and held.held_keys == expected_keys
    released = mapper.map(motion(button=False), profile)
    assert released.held_buttons == released.held_keys == ()


def test_directional_mouse_button_releases_and_caller_mapping_is_copied():
    mapper = DeviceProfileMapper()
    bindings = {"mouse": {"right": "mouse_middle"}}
    mapper.set_control_bindings(bindings)
    bindings["mouse"]["right"] = "key_a"
    profile = profile_by_name("mouse")
    assert mapper.map(motion(tilt_pitch_deg=100.), profile).held_buttons == ("mouse_middle",)
    assert mapper.map(motion(), profile).held_buttons == ()
    mapper.set_control_bindings(None)
    assert mapper.map(motion(tilt_pitch_deg=100.), profile).held_buttons == ()
