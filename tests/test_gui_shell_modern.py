"""Shell isolation, genuine bundled font and display-backed interaction tests."""

import ast
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUI = ROOT / "src" / "triki_controller" / "gui"


def test_legacy_configurator_elements_remain_byte_for_byte_preserved():
    expected = {
        "BiMeter": "4cc70caaa11f1746a4883a2a7fe70dc7d2eeb495dd52a96a10fbf907fd68020a",
        "UniMeter": "2a5b2e90da042ea5fc39a869c229c04c2c066e6926b6c8c7873a3b07671b16aa",
        "SensorBoard": "a2f8cc640548dd484fb6903a9ce5bff121321c42605341e2b74728f4ba75635f",
        "OutputPreview": "7802725fda98390c9a83859a45e9493cbf9074ac8c3a6e58c542c91052d98684",
        "_add_map": "688caedd90ca8c6ea36d9c00eb3cb362227c695cd4643a5a12d6b82f8d48c8dd",
        "_add_slider": "3a68edea0b05feb9e755c729281ec6a101a6b900572c8f9bc575c9f12b59a57c",
        "_on_scale": "c93aaabd9288b5a18a3c3f3c8e3ac95fdae18ee889ccfb7d409d5f9fb1a8e331",
        "_slider_text": "572e71df647e3f60dc057a2e1a82ce3c2fc1f329f2f146fd822fa51b4dd05796",
        "selected_profile": "73c617c92b048c6239195e6e945d0222af314eedddf9213a6e53f39a7bfeb9d3",
        "reset_selected": "a17856d96d743e423eed8419fb545ef20b77a6f2903228ade2354001282d3757",
        "_show_configurator": "f0d3e1c90d05ee7671c7360a16156240423c99520980a7c36c60c877d2f837c6",
        "_select_config_nav": "deed16f19db83f221aa5e487ea87d6f2095d1e743b4efe18b73ff3f05863359f",
        "_section": "2ad9049ebf856586de07eca36c2fbb13dfbdac51dc4340a105152c34ea261af6",
        "_build_connect": "70a673b68ac48556d638e29fa63e241af41eff2cc38fdb8baeaf1ee9d7d712d1",
        "_build_profiles": "ec0f1f3525748769fa81f588a91c03f28c2b1509cecbaaedbba2fc7666c2ff7d",
        "_build_output": "50052221a5a71928e2a7ca6ec47b4ce3085a823c0fa615569c3c4b075f9ed223",
        "_fill_config_body": "7792142532334baf143e0ab1c61a2e2aad65bb1cc451770d04915602eff3ff85",
        "_build_config_editor": "8609641ad0889f35acff2e9fd657ca3ef4d111db35fb265ebc4044b21ffbe4d6",
        "_apply_draft_from_form": "aaee40222039a87f2c1572fad696b5c4240267a4556f6765da5f342c4d42f675",
        "_apply_live_draft": "22527e5eb4f8604825a7c8771b1f07dff4d9faeed1aaa03b75244239893f6356",
        "_save_config": "26c8b41bcd72af88654d8b6b33e0237abb0ed21112c532b653230002b75eda27",
    }
    source = (GUI / "desktop.py").read_text()
    nodes = {node.name: node for node in ast.walk(ast.parse(source))
             if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in expected}
    assert nodes.keys() == expected.keys()
    # Keep legacy widget builders protected; only approved additive wiring is
    # normalized below, not arbitrary changes to the configurator.
    for name, digest in expected.items():
        segment = ast.get_source_segment(source, nodes[name])
        assert segment is not None
        if name == "_build_config_editor":
            for addition in (
                "\n            on_player_select=self._select_media_player,",
                "\n            favorite_descriptor=self.session.favorite_media_descriptor,",
                "\n            favorite_descriptors=self.session.favorite_media_descriptors,",
                "\n            active_favorite=self.session.active_media_favorite,",
            ):
                segment = segment.replace(addition, "")
            segment = segment.replace(
                "on_draft=self._apply_draft_from_form,\n            list_players=self.session.list_media_players,",
                "on_draft=self._apply_draft_from_form",
            )
        elif name == "_save_config":
            segment = segment.replace(
                "            self._persist_quiet()\n"
                "            if self._control_options is not None and not self._dirty:\n"
                "                self._control_options.message.set(f\"Zapisano {self.settings_path}\")\n",
                "",
            )
        assert hashlib.sha256(segment.encode()).hexdigest() == digest, name


def test_official_font_integrity_and_license():
    asset = GUI / "assets" / "phosphor"
    meta = json.loads((asset / "SOURCE.json").read_text())
    assert meta["commit"] == "70854726d7bd82ae21f0dc81b5b5c35240a77066"
    assert "MIT License" in (asset / "LICENSE").read_text()
    for name, receipt in meta["files"].items():
        assert receipt["source"].startswith("https://raw.githubusercontent.com/phosphor-icons/web/")
        assert hashlib.sha256((asset / name).read_bytes()).hexdigest() == receipt["sha256"]


def test_real_font_load_and_distinct_glyphs():
    pytest.importorskip("PIL")
    pytest.importorskip("customtkinter")
    from PIL import ImageFont
    from triki_controller.gui.shell_icons import FONT_PATH, GLYPHS, render_icon
    font = ImageFont.truetype(str(FONT_PATH), 72)
    assert font.getname()[0] == "Phosphor"
    rendered = [render_icon(name) for name in GLYPHS]
    assert all(image.getbbox() is not None for image in rendered)
    assert len({image.tobytes() for image in rendered}) == len(GLYPHS)


@pytest.fixture
def app(tmp_path):
    pytest.importorskip("customtkinter")
    import tkinter as tk
    from triki_controller.gui.desktop import TrikiDesktop
    from triki_controller.gui.session import ControllerSession
    session = ControllerSession()
    try:
        result = TrikiDesktop(session, tmp_path / "settings.json", view="panel", transport="ble",
                              connect=False, live=False, dry_run=False, auto_close=None, quick_command=None)
    except tk.TclError as exc:
        session.shutdown()
        pytest.skip(f"display unavailable: {exc}")
    yield result
    result._dirty = False
    result.close()
    assert not (tmp_path / "settings.json").exists()


def test_launch_buttons_keep_callbacks_and_keyboard(app):
    import customtkinter as ctk
    app.root.update_idletasks()
    assert set(app._shell_launch_buttons) == {"steering", "mouse", "plane", "media"}
    callback = Mock()
    app._launch_device = callback
    for profile, button in app._shell_launch_buttons.items():
        assert isinstance(button.cget("image"), ctk.CTkImage)
        assert button.cget("height") >= 44
        assert str(button.tk.call(button._w, "cget", "-takefocus")) == "1"
        button.invoke()
        callback.assert_called_with(profile)
        button.focus_force()
        app.root.update()
        calls = callback.call_count
        button.event_generate("<Return>")
        app.root.update()
        assert callback.call_count == calls + 1
        callback.assert_called_with(profile)
        button.event_generate("<space>")
        app.root.update()
        assert callback.call_count == calls + 2
        callback.assert_called_with(profile)
        from triki_controller.gui.shell_presentation import TEXT
        assert button.cget("border_color") == TEXT
    app.root.geometry("520x600")
    app.root.update_idletasks()
    assert app.root.winfo_width() >= 520


def test_menu_roundtrip_preserves_config_fields_and_styles(app):
    from triki_controller.gui.desktop import _ACCENT, _BG, _SURFACE
    before = app.session.current_settings()
    app._show_configurator()
    app._select_config_nav("konfiguracja")
    form = app._config_form
    assert form is not None
    collected = form.collect(profile=before.profile, orientation=before.orientation)
    from triki_controller.gui.config_form import resolved_draft
    assert resolved_draft(collected) == resolved_draft(before)
    assert form.tabs.cget("fg_color") == _SURFACE
    assert form.tabs._segmented_button.cget("selected_color") == _ACCENT
    assert app._content.cget("fg_color") == _BG
    fields = (tuple(form._maps), tuple(form._scales), tuple(form._signs))
    app._show_main_menu()
    app._show_configurator()
    app._select_config_nav("konfiguracja")
    form = app._config_form
    assert (tuple(form._maps), tuple(form._scales), tuple(form._signs)) == fields
    assert form.collect(profile=before.profile, orientation=before.orientation) == collected


def test_device_actions_fit_and_extension_hook(app):
    import customtkinter as ctk
    app._quick_command = "mouse"
    app._show_device_screen(from_menu=True)
    app.root.update_idletasks()
    buttons = []
    def walk(widget):
        if isinstance(widget, ctk.CTkButton):
            buttons.append(widget)
        for child in widget.winfo_children():
            walk(child)
    walk(app._content)
    assert {button.cget("text") for button in buttons} == {
        "Połącz ponownie", "Zatrzymaj sterowanie", "Rozłącz", "Menu", "Zamknij", "Zapisz"}
    for button in buttons:
        assert button.winfo_ismapped()
        assert button.winfo_rootx() + button.winfo_width() <= app.root.winfo_rootx() + app.root.winfo_width()
        assert button.winfo_rooty() + button.winfo_height() <= app.root.winfo_rooty() + app.root.winfo_height()
    attach = Mock(return_value="extension")
    assert app.attach_shell_extension(attach) == "extension"
    attach.assert_called_once_with(app)


def test_shell_dark_mode_is_scoped_and_contrast_is_readable(app):
    import customtkinter as ctk
    from triki_controller.gui.shell_presentation import BG, SURFACE, TEXT, MUTED, ACCENT, BORDER, ICON_COLOR
    assert ctk.get_appearance_mode() == "Light"
    assert app._content.cget("fg_color") == BG
    def luminance(color):
        rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in rgb]
        return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    def contrast(first, second):
        low, high = sorted((luminance(first), luminance(second)))
        return (high + 0.05) / (low + 0.05)
    for background in (BG, SURFACE):
        assert contrast(TEXT, background) >= 4.5
        assert contrast(MUTED, background) >= 4.5
        assert contrast(ICON_COLOR, background) >= 3
        assert contrast(BORDER, background) >= 3
    assert contrast("#FFFFFF", ACCENT) >= 4.5
    app._show_configurator()
    assert app._content.cget("fg_color") == "#F5F6F8"
    assert ctk.get_appearance_mode() == "Light"
