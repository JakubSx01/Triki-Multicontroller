"""Real Tk player choices override startup priority; draft edits do not."""
from dataclasses import replace
from unittest.mock import Mock

import pytest

from triki_controller.gui.desktop import TrikiDesktop
from triki_controller.gui.media_favorite import favorite_selector
from triki_controller.gui.session import ControllerSession, OutputMode
from triki_controller.gui.settings import GuiSettings
from triki_controller.output.trace import TraceOutput
from tests.test_gui_desktop import _streaming

FAVORITE = {'platform': 'mpris', 'app_id': 'spotify', 'label': 'Spotify'}
PIN = 'spotify.instance1'


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    import evdev
    monkeypatch.setattr(evdev, 'UInput', Mock(side_effect=AssertionError('native input forbidden')))
    apps = []

    def make(route, player=None):
        opened = []

        class RecordingTrace(TraceOutput):
            def open(self, capabilities):
                opened.append(dict(capabilities))
                super().open(capabilities)

        class InertCatalog:
            def list_media_players(self):
                return [(PIN, 'Spotify')]

            def favorite_media_descriptor(self, player):
                assert player == PIN
                return dict(FAVORITE)

            def close(self):
                pass

        session = ControllerSession(
            settings=GuiSettings(profile='media', media_player=player, media_favorite=FAVORITE),
            output_factory=lambda live: InertCatalog() if live else RecordingTrace())
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
        app._dirty = False
        return app, options, opened

    yield make
    for app in apps:
        app._dirty = False
        for timer in app.root.tk.call('after', 'info'):
            app.root.tk.call('after', 'cancel', timer)
        app.close()


def activation_target(app, opened):
    _streaming(app.session)  # Inject a transport event, never connect to hardware.
    assert app.session.start_output(live=False) is None
    target = opened[-1]['media_player']
    app.session.stop_output()
    return target


@pytest.mark.parametrize('route', ['device', 'config'])
@pytest.mark.parametrize('player,label', [(None, 'Automatycznie'), (PIN, 'Spotify')])
def test_explicit_same_value_choice_clears_startup_priority(make_app, route, player, label):
    app, options, opened = make_app(route, player)
    assert activation_target(app, opened) == favorite_selector(FAVORITE)
    options.player_menu._dropdown_callback(label)
    assert app.session.current_settings().media_player == player
    assert options.settings.media_player == player
    assert activation_target(app, opened) == player
    assert not app.settings_path.exists()
    assert not app._dirty  # Session-only override of an unchanged persisted value.


@pytest.mark.parametrize('route', ['device', 'config'])
@pytest.mark.parametrize('dirty', [False, True])
def test_rejected_choice_restores_menu_and_keeps_session_and_dirty_state(make_app, route, dirty):
    app, options, opened = make_app(route)
    app._dirty = dirty
    app.session.select_media_player = Mock(return_value='Odtwarzacz odrzucił wybór')
    options.player_menu._dropdown_callback('Spotify')
    app.session.select_media_player.assert_called_once_with(PIN)
    assert options.player_menu.get() == 'Automatycznie'
    assert options.settings.media_player is None
    assert app.session.current_settings().media_player is None
    assert options.message.get() == 'Odtwarzacz odrzucił wybór'
    assert app._dirty is dirty
    assert activation_target(app, opened) == favorite_selector(FAVORITE)
    assert not app.settings_path.exists()


@pytest.mark.parametrize('route', ['device', 'config'])
def test_favorite_only_edit_refresh_and_collect_preserve_startup_priority(make_app, route):
    app, options, opened = make_app(route)
    select = Mock(wraps=app.session.select_media_player)
    app.session.select_media_player = select
    assert activation_target(app, opened) == favorite_selector(FAVORITE)
    options.refresh_button.invoke()
    options.collect(app.session.current_settings())
    options.clear_favorite_button.invoke()
    assert app.session.current_settings().media_favorite is None
    assert options.settings.media_favorite is None
    assert app.session.snapshot().output_mode == OutputMode.OFF
    select.assert_not_called()
    assert activation_target(app, opened) == favorite_selector(FAVORITE)
    assert len(opened) == 2  # No favorite edit or observation opened output.
    assert not app.settings_path.exists()


@pytest.mark.parametrize('route', ['device', 'config'])
def test_changed_choice_marks_dirty_and_survives_later_draft_apply(make_app, route):
    app, options, opened = make_app(route)
    options.player_menu._dropdown_callback('Spotify')
    assert options.settings.media_player == PIN
    assert app.session.current_settings().media_player == PIN
    assert app._dirty
    options.clear_favorite_button.invoke()
    assert app.session.current_settings().media_player == PIN
    assert activation_target(app, opened) == PIN
    assert not app.settings_path.exists()


def test_default_editor_keeps_existing_draft_callback_contract(make_app):
    from triki_controller.gui.control_options import ControlOptions
    app, _, _ = make_app('device')
    changed = Mock()
    options = ControlOptions(app.root, GuiSettings(profile='media'), on_change=changed,
                             list_players=lambda: [(PIN, 'Spotify')])
    options.player_menu._dropdown_callback('Spotify')
    assert options.settings.media_player == PIN
    changed.assert_called_once_with(replace(GuiSettings(profile='media'), media_player=PIN))


def test_auto_policy_does_not_claim_startup_favorite_allows_shaking(make_app):
    _, options, _ = make_app('device')
    assert 'ulubiony' in options.gesture_policy.get().lower()
    assert 'ręcznie' in options.gesture_policy.get().lower()
