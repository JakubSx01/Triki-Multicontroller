"""Public settings compatibility and explicit persistence seams."""
import pytest

from triki_controller.gui.settings import GuiSettings, SettingsError, parse_settings


def test_schema_one_defaults_and_new_controls_round_trip():
    old = parse_settings({"schema_version": 1})
    assert old.media_gestures_enabled is True
    assert old.media_player is None
    assert old.control_bindings == {}
    settings = GuiSettings(media_gestures_enabled=False, media_player="org.mpris.MediaPlayer2.vlc",
                           control_bindings={"mouse": {"left": "key_a", "button": "mouse_middle"}})
    assert parse_settings(settings.to_json()) == settings


@pytest.mark.parametrize("fields", [
    {"media_gestures_enabled": 1}, {"media_player": False}, {"media_player": ""},
    {"control_bindings": {"media": {"left": "key_a"}}},
    {"control_bindings": {"mouse": {"yaw": "key_a"}}},
    {"control_bindings": {"mouse": {"left": "key_f24"}}},
    {"control_bindings": {"mouse": []}}, {"control_bindings": []},
])
def test_settings_reject_invalid_controls(fields):
    with pytest.raises(SettingsError):
        parse_settings({"schema_version": 1, **fields})


def test_explicit_save_load_preserves_controls_without_touching_default_path(tmp_path, monkeypatch):
    from triki_controller.gui.settings import save_settings, load_settings
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "untouched-user-config"))
    settings = GuiSettings(media_gestures_enabled=False, media_player="vlc",
                           control_bindings={"steering": {"button": "off", "forward": "key_w"}})
    path = tmp_path / "explicit-test-settings.json"
    assert save_settings(settings, path) == path
    assert load_settings(path) == settings
    assert not (tmp_path / "untouched-user-config").exists()


@pytest.mark.parametrize("bindings", [{"media": {}}, {"plane": {"yaw": "key_a"}}, {"mouse": {"button": "bogus"}}])
def test_serializer_also_rejects_unknown_profiles_sources_actions(bindings):
    with pytest.raises(ValueError):
        GuiSettings(control_bindings=bindings).to_json()


def test_legacy_axis_and_threshold_settings_migrate_without_new_fields():
    old = parse_settings({"schema_version": 1, "profile": "mouse", "thresholds": {"mouse": {"mouse_px_per_sec": 800.}},
                          "axis_map": {"plane": {"x": "roll"}}})
    assert old.thresholds["mouse"]["mouse_x_px_per_sec"] == 800.
    assert old.thresholds["mouse"]["mouse_y_px_per_sec"] == 800.
    assert old.axis_map["plane"]["x"] == "roll"
    assert old.media_gestures_enabled is True and old.media_player is None
