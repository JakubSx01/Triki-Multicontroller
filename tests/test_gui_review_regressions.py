"""Independent-review regressions exercised on real Tk with inert output."""
import tkinter as tk
from unittest.mock import Mock

import pytest

from tests.test_device_switch_ui import app
from tests.test_gui_desktop import _streaming
from tests.gui_tk_harness import control_size, settle
from triki_controller.core.models import ConnectionState
from triki_controller.gui.session import OutputMode
from triki_controller.gui.shell_presentation import refresh_device_actions


@pytest.mark.parametrize('state', [ConnectionState.CONNECTING, ConnectionState.SCANNING])
@pytest.mark.parametrize('live', [False, True])
def test_pending_stop_revokes_output_intent_before_streaming(app, state, live):
    app.dry_run = not live
    app._launch_device('mouse')
    settle(app)
    app.session._state = state
    app._refresh()
    start = Mock(wraps=app.session.start_output)
    app.session.start_output = start
    assert app.session.snapshot().output_mode == OutputMode.OFF
    assert app._autostart.enabled
    assert app._stop_button.cget('state') == 'normal'
    app._stop_button.invoke()
    app._refresh()
    assert not app._autostart.enabled
    assert app._stop_button.cget('state') == 'disabled'
    _streaming(app.session)
    app._refresh()
    app._refresh()
    start.assert_not_called()
    assert app.session.snapshot().output_mode == OutputMode.OFF
    app.session.disconnect.assert_not_called()
    assert not app.settings_path.exists()
    print('PENDING_STOP', state.value, live, 'start_calls', start.call_args_list)


@pytest.mark.parametrize('constructor_dry_run', [False, True])
@pytest.mark.parametrize('previous_live', [False, True])
def test_resume_preserves_last_running_mode(app, constructor_dry_run, previous_live):
    app.dry_run = constructor_dry_run
    app._launch_device('mouse')
    settle(app)
    _streaming(app.session)
    from triki_controller.output.trace import TraceOutput
    class InertIntentSink(TraceOutput):
        # Exercise session LIVE intent without allocating a native input device.
        def open(self, capabilities):
            super().open(dict(capabilities, claim_uinput=False))
    app.session._output_factory = lambda live: InertIntentSink()
    app._autostart.enabled = False
    (app._on_live if previous_live else app._on_dry)()
    previous = OutputMode.LIVE if previous_live else OutputMode.DRY_RUN
    assert app.session.snapshot().output_mode == previous
    app._refresh()
    app._stop_button.invoke()
    app._refresh()
    assert app.session.snapshot().output_mode == OutputMode.OFF
    assert app._resume_button.cget('text') == ('Wznów' if previous_live else 'Wznów próbne')
    start = Mock(wraps=app.session.start_output)
    app.session.start_output = start
    app._resume_button.invoke()
    app._refresh()
    start.assert_called_once_with(live=previous_live)
    assert app.session.snapshot().output_mode == previous
    app.session.connect.assert_not_called()
    app.session.disconnect.assert_not_called()
    print('RESTART_MODE', constructor_dry_run, previous.value, start.call_args_list)


def inside(app, widget):
    assert widget.winfo_ismapped()
    x = widget.winfo_rootx() - app.root.winfo_rootx()
    y = widget.winfo_rooty() - app.root.winfo_rooty()
    assert 0 <= x and 0 <= y
    assert x + widget.winfo_width() <= app.root.winfo_width()
    assert y + widget.winfo_height() <= app.root.winfo_height()


@pytest.mark.parametrize('repetitions', [1, 5, 10, 20, 40])
def test_long_feedback_preserves_actions_and_full_keyboard_access(app, repetitions):
    app._launch_device('mouse')
    control_size(app, (520, 600))
    text = 'Błąd: ' + 'Nie można otworzyć urządzenia. ' * repetitions
    app._status.set(text)
    settle(app)
    for button in app._device_action_buttons:
        inside(app, button)
    assert app._shell_feedback.winfo_height() <= 72
    feedback = app._shell_feedback
    assert feedback.get('1.0', 'end-1c') == text
    assert feedback._textbox.cget('state') == 'disabled'
    tk.Misc.focus_force(feedback._textbox)
    settle(app)
    feedback._textbox.event_generate('<Control-End>')
    settle(app)
    assert feedback._textbox.dlineinfo('end-1c') is not None
    assert feedback._textbox.yview()[1] == 1.0
    print('LONG_FEEDBACK', len(text), 'client', (app.root.winfo_width(), app.root.winfo_height()),
          'height', feedback.winfo_height(), 'actions', [bool(b.winfo_ismapped()) for b in app._device_action_buttons],
          'full_text', feedback.get('1.0', 'end-1c') == text, 'end_visible', feedback._textbox.dlineinfo('end-1c') is not None)
    assert not app.settings_path.exists()


def test_feedback_binding_rebuild_cleans_old_trace_and_updates_new_widget(app):
    app._launch_device('mouse')
    settle(app)
    traces = app._status.trace_info()
    app._function_menu._command('Multimedia')
    settle(app)
    assert len(app._status.trace_info()) == len(traces)
    text = 'Błąd\npełne szczegóły\nkoniec'
    app._status.set(text)
    settle(app)
    assert app._shell_feedback.get('1.0', 'end-1c') == text


def test_long_connection_error_is_disclosed_without_hiding_actions(app):
    import customtkinter as ctk
    app._launch_device('mouse')
    control_size(app, (520, 600))
    text = 'Błąd: ' + 'Nie można otworzyć urządzenia. ' * 40
    app.session._state = ConnectionState.ERROR
    app._detail.set(text)
    refresh_device_actions(app)
    settle(app)
    for button in app._device_action_buttons:
        inside(app, button)
    assert 'Diagnostyka' in app._shell_connection_hint.get()
    tab = app._shell_tab_buttons['Diagnostyka']
    tk.Misc.focus_force(tab)
    settle(app)
    tab.event_generate('<Return>')
    settle(app)
    page = app._shell_pages['Diagnostyka']
    labels = [child for child in page.winfo_children() if isinstance(child, ctk.CTkLabel)]
    detail = next(label for label in labels if str(label.cget('textvariable')) == str(app._detail))
    assert detail._label.cget('text') == text
    canvas = page._parent_canvas
    canvas.yview_moveto(1.0)
    settle(app)
    last_line_y = detail.winfo_rooty() + detail.winfo_height()
    # The whole detail precedes secondary actions in this independently scrollable page.
    assert last_line_y <= canvas.winfo_rooty() + canvas.winfo_height()
    assert app._shell_active_page == 'Diagnostyka'
    for button in app._device_action_buttons:
        inside(app, button)
    print('LONG_CONNECTION_ERROR', len(text), 'full_detail', detail._label.cget('text') == text,
          'actions', [bool(b.winfo_ismapped()) for b in app._device_action_buttons])
