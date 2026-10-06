"""Display-backed navigation contract: a function is not a connection."""
from dataclasses import replace
import tkinter as tk
from unittest.mock import Mock

import pytest

from tests.gui_tk_harness import control_size, settle
from triki_controller.core.models import ConnectionState
from triki_controller.gui.desktop import TrikiDesktop
from triki_controller.gui.session import ControllerSession
from triki_controller.output.trace import TraceOutput


@pytest.fixture
def app(tmp_path, monkeypatch):
    import evdev
    monkeypatch.setattr(evdev, 'UInput', Mock(side_effect=AssertionError('real input forbidden')))
    opened_profiles = []
    class CountingTrace(TraceOutput):
        def open(self, capabilities):
            opened_profiles.append(capabilities['mode'])
            super().open(capabilities)
    def output_factory(live):
        return CountingTrace()
    session = ControllerSession(output_factory=output_factory)
    session.connect = Mock(return_value=None)
    session.disconnect = Mock()
    desktop = TrikiDesktop(session, tmp_path / 'settings.json', view='panel', transport='ble',
                           connect=False, live=False, dry_run=True, auto_close=None, quick_command=None)
    desktop._confirm_discard = Mock(return_value=True)
    desktop._trace_open_profiles = opened_profiles
    yield desktop
    desktop._dirty = False
    for timer in desktop.root.tk.call('after', 'info'):
        desktop.root.tk.call('after', 'cancel', timer)
    desktop.close()


def test_device_menu_does_not_disconnect_and_cancel_does_not_stop(app):
    app._launch_device('mouse')
    app.root.update_idletasks()
    stop = Mock(wraps=app.session.stop_output)
    app.session.stop_output = stop
    app._dirty = True
    app._confirm_discard.return_value = False
    app._back_to_menu_from_device()
    assert app._screen == 'device'
    stop.assert_not_called()
    app.session.disconnect.assert_not_called()
    app._confirm_discard.return_value = True
    app._back_to_menu_from_device()
    assert app._screen == 'menu'
    assert stop.call_count == 1
    app.session.disconnect.assert_not_called()


@pytest.mark.parametrize('state', [ConnectionState.STREAMING, ConnectionState.CONNECTING, ConnectionState.SCANNING])
def test_launch_reuses_streaming_or_pending_connection(app, state):
    snap = replace(app.session.snapshot(), connection=state)
    app.session.snapshot = lambda: replace(snap, profile_name=app.session.current_settings().profile)
    app._launch_device('media')
    app._launch_device('plane')
    app._startup_connect()
    assert app.session.current_settings().profile == 'plane'
    app.session.connect.assert_not_called()
    app.session.disconnect.assert_not_called()


def test_function_selector_keyboard_and_narrow_layout(app):
    app._launch_device('mouse')
    control_size(app, (620, 700))
    menu = app._function_menu
    tk.Misc.focus_force(menu)
    settle(app)
    menu.event_generate('<Right>')
    settle(app)
    assert app.session.current_settings().profile == 'plane'
    assert app._function_menu.get() == 'Joystick'
    assert app.root.focus_get() == app._function_menu
    app.session.disconnect.assert_not_called()
    control_size(app, (620, 700))
    for button in app._device_action_buttons:
        assert button.winfo_ismapped()
        assert button.winfo_rootx() >= app.root.winfo_rootx()
        assert button.winfo_rootx() + button.winfo_width() <= app.root.winfo_rootx() + 620
        assert button.winfo_rooty() + button.winfo_height() <= app.root.winfo_rooty() + 700
    assert not app.settings_path.exists()


def test_stale_launch_callback_and_stop_cannot_arm_after_navigation(app):
    app._launch_device('mouse')
    app._back_to_menu_from_device()
    app._connect_device_if_needed()
    app.session.connect.assert_not_called()
    app._launch_device('media')
    app._on_stop()
    app._connect_device_if_needed()
    assert not app._autostart.enabled
    app.session.connect.assert_not_called()


def test_function_rebuild_keeps_existing_window_geometry(app):
    app._launch_device('mouse')
    control_size(app, (620, 700))
    app._function_menu._command('Multimedia')
    settle(app)
    assert (app.root.winfo_width(), app.root.winfo_height()) == (620, 700)
    assert 'Zapisz' in {button.cget('text') for button in app._device_action_buttons}


def test_streaming_switch_arms_once_and_menu_relaunch_never_reconnects(app):
    from tests.test_gui_desktop import _streaming
    _streaming(app.session)
    app._launch_device('media')
    app._refresh()
    assert app._trace_open_profiles == ['media']
    app._function_menu._command('AirMouse')
    app._refresh()
    app._refresh()
    assert app._trace_open_profiles == ['media', 'mouse']
    app._back_to_menu_from_device()
    app._launch_device('plane')
    app._refresh()
    app._refresh()
    assert app._trace_open_profiles == ['media', 'mouse', 'plane']
    app.session.connect.assert_not_called()
    app.session.disconnect.assert_not_called()
