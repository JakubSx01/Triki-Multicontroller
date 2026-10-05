"""Public session observations and real Tk effective/startup target state."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from triki_controller.gui.session import ControllerSession
from triki_controller.gui.settings import GuiSettings
from triki_controller.output.trace import TraceOutput

FAVORITE = {'platform': 'mpris', 'app_id': 'spotify', 'label': 'Spotify'}
OTHER = {'platform': 'mpris', 'app_id': 'vlc', 'label': 'VLC'}
PIN = 'spotify.instance1'
OTHER_PIN = 'vlc.instance1'


def test_active_favorite_query_is_detached_observation_of_session_priority():
    output = TraceOutput()
    factory = Mock(return_value=output)
    session = ControllerSession(settings=GuiSettings(profile='media', media_favorite=FAVORITE),
                                output_factory=factory)
    factory.reset_mock()
    first = session.active_media_favorite()
    assert first == FAVORITE
    first['label'] = 'Changed copy'
    assert session.active_media_favorite() == FAVORITE
    assert session.apply_settings(replace(session.current_settings(), media_favorite=OTHER)) is None
    assert session.current_settings().media_favorite == OTHER
    assert session.active_media_favorite() == FAVORITE
    assert session.select_media_player(None) is None
    assert session.active_media_favorite() is None
    factory.assert_not_called()
    assert not output.opened
    assert output.receipts == []


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    from triki_controller.gui.desktop import TrikiDesktop
    import tkinter.messagebox
    monkeypatch.setattr(tkinter.messagebox, 'askyesno', lambda *args, **kwargs: True)
    apps = []

    def make(route, player=None, favorite=FAVORITE, gestures=True, available=True):
        class Catalog:
            def list_media_players(self):
                return [(PIN, 'Spotify'), (OTHER_PIN, 'VLC')] if available else [(OTHER_PIN, 'VLC')]

            def favorite_media_descriptor(self, identifier):
                return dict(FAVORITE if identifier == PIN else OTHER)

            def close(self):
                pass

        trace = TraceOutput()
        session = ControllerSession(
            settings=GuiSettings(profile='media', media_player=player, media_favorite=favorite,
                                 media_gestures_enabled=gestures),
            output_factory=lambda live: Catalog() if live else trace)
        session.connect = Mock(side_effect=AssertionError('BLE forbidden'))
        app = TrikiDesktop(session, tmp_path / f'{len(apps)}.json', view='panel', transport='ble',
                           connect=False, live=False, dry_run=True, auto_close=None, quick_command=None)
        apps.append(app)
        app._confirm_discard = lambda: True
        if route == 'device':
            app._quick_command = 'music'
            app._show_device_screen(from_menu=True)
            options = app._control_options
        else:
            app._show_configurator()
            app._select_config_nav('konfiguracja')
            options = app._config_form.control_options['media']
        app.root.update_idletasks()
        return app, options, trace

    yield make
    for app in apps:
        app._dirty = False
        for timer in app.root.tk.call('after', 'info'):
            app.root.tk.call('after', 'cancel', timer)
        app.close()


@pytest.mark.parametrize('route', ['device', 'config'])
@pytest.mark.parametrize('player', [None, PIN])
def test_effective_startup_favorite_is_separate_from_manual_selection(make_app, route, player):
    app, options, trace = make_app(route, player=player)
    assert options.gesture_toggle.cget('state') == 'disabled'
    assert options.gestures_enabled.get()
    assert options.player_menu.get() == ('Automatycznie' if player is None else 'Spotify')
    assert options.session_target.get() == 'Cel sesji: ulubiony Spotify (priorytet startowy)'
    assert 'ulubiony' in options.gesture_policy.get().lower()
    assert 'ręcznie' in options.gesture_policy.get().lower()
    assert app.session.active_media_favorite() == FAVORITE
    assert not trace.opened
    assert not app.settings_path.exists()


@pytest.mark.parametrize('route', ['device', 'config'])
@pytest.mark.parametrize('gestures', [False, True])
def test_explicit_auto_restores_saved_gesture_preference(make_app, route, gestures):
    app, options, trace = make_app(route, gestures=gestures)
    options.gesture_toggle.toggle()
    assert app.session.current_settings().media_gestures_enabled is gestures
    options.player_menu._dropdown_callback('Automatycznie')
    assert app.session.active_media_favorite() is None
    assert options.session_target.get() == 'Cel sesji: Automatycznie'
    assert options.gesture_toggle.cget('state') == 'normal'
    assert options.gestures_enabled.get() is gestures
    assert app.session.current_settings().media_gestures_enabled is gestures
    assert not trace.opened


@pytest.mark.parametrize('route', ['device', 'config'])
def test_explicit_same_pin_removes_favorite_priority_but_keeps_manual_gesture_block(make_app, route):
    app, options, trace = make_app(route, player=PIN)
    options.player_menu._dropdown_callback('Spotify')
    assert app.session.active_media_favorite() is None
    assert options.session_target.get() == f'Cel sesji: wybór ręczny ({PIN})'
    assert options.gesture_toggle.cget('state') == 'disabled'
    assert app.session.current_settings().media_player == PIN
    assert not trace.opened


@pytest.mark.parametrize('route', ['device', 'config'])
def test_starring_different_next_start_favorite_never_replaces_session_priority(make_app, route):
    app, options, trace = make_app(route, player=OTHER_PIN)
    options.favorite_button.invoke()
    options.refresh_button.invoke()
    collected = options.collect(app.session.current_settings())
    assert collected.media_favorite == OTHER
    assert app.session.current_settings().media_favorite == OTHER
    assert options.favorite_status.get().startswith('Następny start: VLC')
    assert options.session_target.get() == 'Cel sesji: ulubiony Spotify (priorytet startowy)'
    assert app.session.active_media_favorite() == FAVORITE
    assert options.gesture_toggle.cget('state') == 'disabled'
    options.clear_favorite_button.invoke()
    assert app.session.current_settings().media_favorite is None
    assert options.session_target.get() == 'Cel sesji: ulubiony Spotify (priorytet startowy)'
    assert not trace.opened
    assert trace.receipts == []
    assert not app.settings_path.exists()


@pytest.mark.parametrize('route', ['device', 'config'])
def test_unavailable_favorite_keeps_pending_session_target_without_substitution(make_app, route):
    app, options, trace = make_app(route, available=False)
    assert options.session_target.get() == 'Cel sesji: ulubiony Spotify (priorytet startowy)'
    assert 'niedostępny' in options.favorite_status.get()
    assert options.player_menu.get() == 'Automatycznie'
    assert options.gesture_toggle.cget('state') == 'disabled'
    assert app.session.active_media_favorite() == FAVORITE
    assert app.session.current_settings().media_player is None
    assert not trace.opened


@pytest.mark.parametrize('route', ['device', 'config'])
def test_no_active_priority_does_not_promote_next_start_draft_into_session_target(make_app, route):
    app, options, trace = make_app(route, player=OTHER_PIN, favorite=None)
    options.favorite_button.invoke()
    options.refresh_button.invoke()
    assert app.session.active_media_favorite() is None
    assert app.session.current_settings().media_favorite == OTHER
    assert options.favorite_status.get().startswith('Następny start: VLC')
    assert options.session_target.get() == f'Cel sesji: wybór ręczny ({OTHER_PIN})'
    options.player_menu._dropdown_callback('Automatycznie')
    assert options.session_target.get() == 'Cel sesji: Automatycznie'
    assert options.gesture_toggle.cget('state') == 'normal'
    assert not trace.opened
