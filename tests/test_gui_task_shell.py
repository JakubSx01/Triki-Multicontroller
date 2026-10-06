"""Real Tk contract tests for the task-first shell; fixtures never use hardware."""
import tkinter as tk
from unittest.mock import Mock

import pytest

from tests.test_device_switch_ui import app
from tests.test_gui_desktop import _streaming
from triki_controller.gui.session import OutputMode
from triki_controller.gui.shell_presentation import refresh_device_actions


from tests.gui_tk_harness import control_size, settle


def inside_root(app, widget):
    assert widget.winfo_ismapped()
    x = widget.winfo_rootx() - app.root.winfo_rootx()
    y = widget.winfo_rooty() - app.root.winfo_rooty()
    assert 0 <= x and 0 <= y
    assert x + widget.winfo_width() <= app.root.winfo_width()
    assert y + widget.winfo_height() <= app.root.winfo_height()


@pytest.mark.parametrize('size', [(520, 600), (620, 700), (1000, 800)])
@pytest.mark.parametrize('profile', ['steering', 'mouse', 'plane', 'media'])
def test_exact_client_geometry_and_fixed_actions(app, profile, size):
    app._launch_device(profile)
    control_size(app, size)
    assert (app.root.winfo_width(), app.root.winfo_height()) == size
    for page in app._shell_pages:
        app._show_shell_page(page)
        settle(app)
        for button in app._device_action_buttons + app._shell_navigation_buttons + list(app._shell_tab_buttons.values()):
            inside_root(app, button)
    assert not app.settings_path.exists()
    app.session.connect.assert_not_called()


def test_stop_resume_uses_existing_trace_output_without_reconnect(app):
    _streaming(app.session)
    app._launch_device('mouse')
    app._refresh()
    assert app.session.snapshot().output_mode == OutputMode.DRY_RUN
    assert app._stop_button.cget('state') == 'normal'
    assert app._resume_button.cget('state') == 'disabled'
    app._stop_button.invoke()
    app._refresh()
    assert app.session.snapshot().output_mode == OutputMode.OFF
    assert app._resume_button.cget('text') == 'Wznów próbne'
    assert app._resume_button.cget('state') == 'normal'
    app._resume_button.invoke()
    app._refresh()
    assert app.session.snapshot().output_mode == OutputMode.DRY_RUN
    app.session.connect.assert_not_called()
    app.session.disconnect.assert_not_called()
    assert not app.settings_path.exists()


def test_primary_connect_and_pending_state_are_truthful(app):
    app._launch_device('mouse')
    settle(app)
    assert app._resume_button.cget('text') == 'Połącz'
    callback = Mock()
    app._on_retry = callback
    app._resume_button.invoke()
    callback.assert_called_once_with()
    from dataclasses import replace
    from triki_controller.core.models import ConnectionState
    snapshot = replace(app.session.snapshot(), connection=ConnectionState.SCANNING)
    app.session.snapshot = lambda: snapshot
    refresh_device_actions(app)
    assert app._resume_button.cget('text') == 'Łączenie…'
    assert app._resume_button.cget('state') == 'disabled'
    app._resume_button.invoke()
    callback.assert_called_once_with()


def test_bindings_disclosed_keyboard_reveals_last_row_and_save_stays_visible(app):
    app._launch_device('mouse')
    control_size(app, (520, 600))
    assert app._shell_active_page == 'Sterowanie'
    assert not app._control_options.winfo_viewable()
    tab = app._shell_tab_buttons['Przypisania']
    tk.Misc.focus_force(tab)
    settle(app)
    tab.event_generate('<Return>')
    settle(app)
    assert app._shell_active_page == 'Przypisania'
    menu = app._control_options.binding_menus['backward']
    tk.Misc.focus_force(menu)
    settle(app)
    canvas = app._shell_pages['Przypisania']._parent_canvas
    assert menu.winfo_rooty() >= canvas.winfo_rooty()
    assert menu.winfo_rooty() + menu.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
    menu.event_generate('<Right>')
    settle(app)
    assert app._dirty
    inside_root(app, app._save_button)
    assert not app.settings_path.exists()
    app._save_button.invoke()
    from triki_controller.gui.settings import load_settings
    saved = load_settings(app.settings_path)
    assert saved is not None
    assert saved.control_bindings['mouse']['backward'] == 'off'
    assert not app._dirty


def test_dirty_cancel_prevents_configurator_navigation_and_stop(app):
    app._launch_device('mouse')
    app._dirty = True
    app._confirm_discard.return_value = False
    stop = Mock(wraps=app.session.stop_output)
    app.session.stop_output = stop
    app._shell_navigation_buttons[-1].invoke()
    assert app._screen == 'device'
    assert app._dirty
    stop.assert_not_called()
    app.session.disconnect.assert_not_called()


def test_menu_last_card_is_keyboard_reachable_at_exact_small_size(app):
    control_size(app, (520, 600))
    callback = Mock()
    app._launch_device = callback
    button = app._shell_launch_buttons['media']
    tk.Misc.focus_force(button)
    settle(app)
    inside_root(app, button)
    ancestor = button.master
    import customtkinter as ctk
    while not isinstance(ancestor, ctk.CTkScrollableFrame):
        ancestor = ancestor.master
    canvas = ancestor._parent_canvas
    assert button.winfo_rooty() >= canvas.winfo_rooty()
    assert button.winfo_rooty() + button.winfo_height() <= canvas.winfo_rooty() + canvas.winfo_height()
    button.event_generate('<Return>')
    settle(app)
    callback.assert_called_once_with('media')


def test_media_gestures_are_disclosed_keyboard_operable_and_not_autosaved(app):
    app._launch_device('media')
    control_size(app, (520, 600))
    assert set(app._shell_pages) == {'Sterowanie', 'Diagnostyka'}
    options = app._control_options
    assert not options.gesture_toggle.winfo_viewable()
    tk.Misc.focus_force(options.gesture_disclosure)
    settle(app)
    options.gesture_disclosure.event_generate('<space>')
    settle(app)
    assert options.gesture_toggle.winfo_viewable()
    tk.Misc.focus_force(options.gesture_toggle)
    settle(app)
    previous = app.session.current_settings().media_gestures_enabled
    options.gesture_toggle.event_generate('<space>')
    settle(app)
    assert app.session.current_settings().media_gestures_enabled != previous
    assert app._dirty
    inside_root(app, app._save_button)
    assert not app.settings_path.exists()
    app.session.connect.assert_not_called()
