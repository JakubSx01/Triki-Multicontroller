"""Real Tk tests for additive controller options; no hardware or real settings."""
import os
import tkinter as tk

import pytest
import customtkinter as ctk

from triki_controller.gui.settings import GuiSettings


@pytest.fixture
def root():
    os.environ.setdefault('DISPLAY', ':0')
    try:
        window = ctk.CTk()
    except tk.TclError as exc:
        pytest.skip(str(exc))
    yield window
    for timer in window.tk.call('after', 'info'):
        window.tk.call('after', 'cancel', timer)
    window.destroy()


def test_profile_editor_starts_legacy_and_emits_only_explicit_selection(root):
    from triki_controller.gui.control_options import ControlOptions, ACTION_LABELS
    changes = []
    options = ControlOptions(root, GuiSettings(profile='mouse'), on_change=lambda settings: changes.append(settings))
    options.pack()
    root.update()
    assert len(options.binding_menus) == 8
    assert options.binding_menus['button'].get() == 'Domyślne'
    assert changes == []
    menu = options.binding_menus['button']
    menu._command(ACTION_LABELS['key_space'])
    assert changes[-1].control_bindings == {'mouse': {'button': 'key_space'}}
    assert changes[-1].profile == 'mouse'


def test_configurator_old_fields_keep_new_options_across_tab_collection(root):
    from triki_controller.gui.desktop import ConfigForm
    settings = GuiSettings(profile='mouse', media_player='missing', media_gestures_enabled=False,
                           control_bindings={'mouse': {'button': 'key_space'}, 'plane': {'left': 'key_a'}})
    form = ConfigForm(root, settings)
    form.pack()
    root.update()
    collected = form.collect(profile='plane', orientation='horizontal')
    assert collected.media_player == 'missing'
    assert not collected.media_gestures_enabled
    assert collected.control_bindings == settings.control_bindings
    assert len(form._maps) > 8


def test_media_refresh_keeps_missing_pin_without_mutating_settings(root):
    from triki_controller.gui.control_options import ControlOptions
    changes = []
    players = [('a', 'Pierwszy')]
    settings = GuiSettings(profile='media', media_player='gone', media_gestures_enabled=False)
    options = ControlOptions(root, settings, on_change=lambda s: changes.append(s), list_players=lambda: players)
    options.pack()
    root.update()
    assert options.player_menu.get() == 'gone (niedostępny)'
    options.refresh_button.invoke()
    assert options.player_menu.get() == 'gone (niedostępny)'
    assert changes == []
    assert not options.gestures_enabled.get()
    assert options.gesture_toggle.cget('state') == 'disabled'
    options.gesture_toggle.toggle()
    assert changes == []
    options.player_menu._command('Automatycznie')
    assert options.gesture_toggle.cget('state') == 'normal'
    options.gesture_toggle.toggle()
    assert changes[-1].media_gestures_enabled
    options.player_menu._command('Pierwszy')
    assert changes[-1].media_player == 'a'
    assert options.gesture_toggle.cget('state') == 'disabled'
    assert 'ręczny' in options.gesture_policy.get().lower()


@pytest.fixture
def app(tmp_path):
    from triki_controller.gui.desktop import TrikiDesktop
    from triki_controller.gui.session import ControllerSession
    from tests.test_control_runtime import PlayerOutput
    session = ControllerSession(settings=GuiSettings(profile='mouse'), output_factory=lambda live: PlayerOutput())
    desktop = TrikiDesktop(session, tmp_path / 'settings.json', view='panel', transport='ble',
                           connect=False, live=False, dry_run=True, auto_close=None, quick_command=None)
    yield desktop
    desktop._dirty = False
    for timer in desktop.root.tk.call('after', 'info'):
        desktop.root.tk.call('after', 'cancel', timer)
    desktop.close()


def test_shell_options_survive_rebuild_and_save_only_on_explicit_action(app):
    from triki_controller.gui.control_options import ACTION_LABELS
    from triki_controller.gui.settings import load_settings
    app._quick_command = 'mouse'
    app._show_device_screen(from_menu=True)
    app.root.update()
    app._control_options.binding_menus['button']._command(ACTION_LABELS['key_space'])
    assert app.session.current_settings().control_bindings == {'mouse': {'button': 'key_space'}}
    assert not app.settings_path.exists()
    app._show_configurator()
    app._select_config_nav('konfiguracja')
    app.root.update()
    form = app._config_form
    form.tabs.set('Joystick')
    form.control_options['plane'].binding_menus['left']._command(ACTION_LABELS['key_a'])
    assert app.session.current_settings().control_bindings == {'mouse': {'button': 'key_space'}, 'plane': {'left': 'key_a'}}
    assert not app.settings_path.exists()
    app._save_config()
    saved = load_settings(app.settings_path)
    assert saved.control_bindings == app.session.current_settings().control_bindings
    app._select_config_nav('podglad')
    app._select_config_nav('konfiguracja')
    assert app._config_form.control_options['mouse'].binding_menus['button'].get() == ACTION_LABELS['key_space']
    assert app._config_form.control_options['plane'].binding_menus['left'].get() == ACTION_LABELS['key_a']


def test_binding_menu_actual_keyboard_event_is_accessible(root):
    from triki_controller.gui.control_options import ControlOptions
    changes = []
    options = ControlOptions(root, GuiSettings(profile='mouse'), on_change=lambda s: changes.append(s))
    options.pack()
    root.update()
    menu = options.binding_menus['button']
    tk.Misc.focus_force(menu)
    root.update()
    menu.event_generate('<Right>')
    root.update()
    assert menu.get() == 'Wyłączone'
    assert len(changes) == 1
    assert changes[0].control_bindings == {'mouse': {'button': 'off'}}
