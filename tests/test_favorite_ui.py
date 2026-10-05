"""Favorite UI is an explicit settings draft, never a player switch or save."""
import tkinter as tk
from unittest.mock import Mock

import customtkinter as ctk
import pytest

from triki_controller.gui.control_options import ControlOptions
from triki_controller.gui.settings import GuiSettings

FAVORITE = {'platform': 'mpris', 'app_id': 'spotify', 'label': 'Spotify'}


@pytest.fixture
def root(monkeypatch):
    import evdev
    monkeypatch.setattr(evdev, 'UInput', Mock(side_effect=AssertionError('real input forbidden')))
    window = ctk.CTk()
    window.geometry('620x700')
    yield window
    for timer in window.tk.call('after', 'info'):
        window.tk.call('after', 'cancel', timer)
    window.destroy()


def test_star_keyboard_edits_favorite_without_changing_manual_player(root):
    changes = []
    options = ControlOptions(root, GuiSettings(profile='media', media_player='spotify.instance1'),
                             list_players=lambda: [('spotify.instance1', 'Spotify')],
                             favorite_descriptor=lambda player: dict(FAVORITE),
                             on_change=lambda settings: changes.append(settings))
    options.pack(fill='x')
    root.update()
    assert changes == []
    assert options.favorite_button.cget('state') == 'normal'
    tk.Misc.focus_force(options.favorite_button)
    root.update()
    options.favorite_button.event_generate('<space>')
    root.update()
    assert changes[-1].media_favorite == FAVORITE
    assert changes[-1].media_player == 'spotify.instance1'
    assert options.favorite_button.cget('text') == 'Ulubiony'
    assert options.favorite_button.cget('border_color') == '#F0F4FC'
    assert 'Zapisz' in options.favorite_status.get()
    options.favorite_button.event_generate('<Return>')
    root.update()
    assert len(changes) == 2
    assert changes[-1].media_favorite is None
    assert options.favorite_button.cget('text') == 'Ustaw ulubiony'


def test_auto_cannot_be_favorited_missing_favorite_visible_and_removable(root):
    changes = []
    settings = GuiSettings(profile='media', media_favorite=FAVORITE)
    options = ControlOptions(root, settings, list_players=lambda: [],
                             favorite_descriptor=lambda player: dict(FAVORITE),
                             on_change=lambda candidate: changes.append(candidate))
    options.pack(fill='x')
    root.update()
    options.refresh_button.invoke()
    assert changes == []
    assert options.favorite_button.cget('state') == 'disabled'
    options.favorite_button.invoke()
    assert changes == []
    assert 'Spotify' in options.favorite_status.get()
    assert 'niedostępny' in options.favorite_status.get()
    options.clear_favorite_button.invoke()
    assert changes[-1].media_favorite is None
    assert changes[-1].media_player is None


def test_descriptor_and_apply_errors_preserve_previous_favorite(root):
    descriptor = Mock(side_effect=ValueError('Tożsamość aplikacji niedostępna'))
    settings = GuiSettings(profile='media', media_player='pid:123', media_favorite=FAVORITE)
    options = ControlOptions(root, settings, list_players=lambda: [('pid:123', 'Nowy')],
                             favorite_descriptor=descriptor)
    options.pack()
    root.update()
    options.favorite_button.invoke()
    assert options.settings == settings
    assert 'niedostępna' in options.message.get()
    options._favorite_descriptor = lambda player: {'platform': 'windows', 'app_id': 'stable.exe', 'label': 'Nowy'}
    options._on_change = lambda settings: 'Nie można zastosować'
    options.refresh_players()
    options.favorite_button.invoke()
    assert options.settings == settings
    assert options.message.get() == 'Nie można zastosować'
    assert 'Spotify' in options.favorite_status.get()


def test_collect_and_configurator_keep_favorite_on_other_profile(root):
    from triki_controller.gui.desktop import ConfigForm
    settings = GuiSettings(profile='mouse', media_favorite=FAVORITE)
    form = ConfigForm(root, settings, favorite_descriptor=lambda player: dict(FAVORITE))
    form.pack(fill='both', expand=True)
    root.update()
    collected = form.collect(profile='plane', orientation='horizontal')
    assert collected.media_favorite == FAVORITE
    media = form.control_options['media']
    media.clear_favorite_button.invoke()
    assert form.collect(profile='mouse', orientation='horizontal').media_favorite is None


def test_shell_draft_survives_function_switch_and_saves_only_explicitly(tmp_path, monkeypatch):
    import evdev
    from triki_controller.gui.desktop import TrikiDesktop
    from triki_controller.gui.session import ControllerSession
    from triki_controller.gui.settings import load_settings
    from triki_controller.output.trace import TraceOutput
    monkeypatch.setattr(evdev, 'UInput', Mock(side_effect=AssertionError('real input forbidden')))
    session = ControllerSession(settings=GuiSettings(profile='media', media_player='spotify.instance1'),
                                output_factory=lambda live: TraceOutput())
    session.list_media_players = lambda: [('spotify.instance1', 'Spotify')]
    session.favorite_media_descriptor = lambda player: dict(FAVORITE)
    session.connect = Mock(side_effect=AssertionError('real BLE forbidden'))
    app = TrikiDesktop(session, tmp_path / 'settings.json', view='panel', transport='ble',
                       connect=False, live=False, dry_run=True, auto_close=None, quick_command=None)
    app._confirm_discard = lambda: True
    try:
        app._quick_command = 'music'
        app._show_device_screen(from_menu=True)
        app._control_options.favorite_button.invoke()
        assert session.current_settings().media_favorite == FAVORITE
        assert not app.settings_path.exists()
        app._launch_device('mouse')
        app._show_configurator()
        app._select_config_nav('konfiguracja')
        assert app._config_form.collect(profile='plane', orientation='horizontal').media_favorite == FAVORITE
        assert not app.settings_path.exists()
        app._save_config()
        assert load_settings(app.settings_path).media_favorite == FAVORITE
    finally:
        app._dirty = False
        for timer in app.root.tk.call('after', 'info'):
            app.root.tk.call('after', 'cancel', timer)
        app.close()
