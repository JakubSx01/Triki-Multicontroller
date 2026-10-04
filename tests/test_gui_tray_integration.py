"""Real Tk lifecycle acceptance with a controlled, thread-backed tray backend."""
from __future__ import annotations

import threading
import time
from unittest.mock import Mock

import pytest

pytest.importorskip("customtkinter")
import tkinter as tk

from triki_controller.gui.desktop import TrikiDesktop
from triki_controller.gui.launch import apply_quick_profile
from triki_controller.gui.session import ControllerSession
from triki_controller.gui import tray as tray_module


class FakeIcon:
    def __init__(self, actions):
        self.actions = actions
        self.visible = False
        self.started = threading.Event()
        self.finished = threading.Event()
        self.stops = 0
        self.setup = None

    def run(self, setup):
        self.run_detached(setup)
        self.finished.wait(5)

    def run_detached(self, setup):
        self.setup = setup
        self.started.set()

    def ready(self):
        assert self.started.wait(2)
        worker = threading.Thread(target=self.setup, args=(self,))
        worker.start()
        worker.join(2)
        assert not worker.is_alive()

    def stop(self):
        self.stops += 1
        self.visible = False
        self.finished.set()


def pump_until(root, predicate, timeout=2):
    deadline = time.monotonic() + timeout
    outcome = []

    def check():
        if predicate():
            outcome.append(True)
            root.quit()
        elif time.monotonic() >= deadline:
            root.quit()
        else:
            root.after(10, check)

    root.after(0, check)
    root.mainloop()
    assert outcome, "Tk lifecycle condition timed out"


def window_close(app):
    app.root.tk.call(app.root.protocol("WM_DELETE_WINDOW"))


@pytest.fixture
def desktop_factory(monkeypatch, tmp_path):
    icons, apps = [], []

    def factory(actions):
        icon = FakeIcon(actions)
        icons.append(icon)
        return icon

    original_init = tray_module.QuickLaunchTray.__init__

    def init(self, *args, **kwargs):
        kwargs["icon_factory"] = factory
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(tray_module.QuickLaunchTray, "__init__", init)
    # Isolate BLE/output polling, not the actual tray's Tk timer or mainloop.
    monkeypatch.setattr(TrikiDesktop, "_startup_connect", lambda self: None)
    monkeypatch.setattr(TrikiDesktop, "_tick", lambda self: None)

    def build(view="quick", command="mouse", auto_close=None):
        session = ControllerSession()
        if view == "quick":
            assert apply_quick_profile(session, command) is None
        path = tmp_path / f"{len(apps)}-settings.json"
        try:
            app = TrikiDesktop(session, path, view=view, transport="fake", connect=False,
                               live=False, dry_run=True, auto_close=auto_close,
                               quick_command=command if view == "quick" else None)
        except tk.TclError as exc:
            session.shutdown()
            pytest.skip(f"display unavailable: {exc}")
        apps.append(app)
        app.root.update_idletasks()
        return app

    yield build, icons
    for app in apps:
        app._dirty = False
        app.close()
        assert not app.settings_path.exists()
    for icon in icons:
        assert icon.finished.is_set()


@pytest.mark.parametrize("command", ["mouse", "wheel", "music", "plane"])
def test_native_quick_commands_auto_attach_one_tray(desktop_factory, command):
    build, icons = desktop_factory
    app = build(command=command)
    before = app.session.current_settings()
    assert len(icons) == 1
    assert app._tray is not None
    assert not app._tray.operational
    assert app.root.state() != "withdrawn"
    icons[0].ready()
    pump_until(app.root, lambda: app._tray.operational)
    assert app.root.state() == "withdrawn"
    assert app.session.current_settings() == before
    assert not app._closed


@pytest.mark.parametrize("view", ["panel", "config"])
def test_non_quick_views_keep_ordinary_window_close(desktop_factory, view):
    build, icons = desktop_factory
    app = build(view=view)
    assert app._tray is None
    assert icons == []
    window_close(app)
    assert app._closed


def test_window_x_hides_without_stopping_session(desktop_factory):
    build, icons = desktop_factory
    app = build()
    icon = icons[0]
    icon.ready()
    pump_until(app.root, lambda: app._tray.operational)
    app._tray.show()
    shutdown = Mock(wraps=app.session.shutdown)
    app.session.shutdown = shutdown
    window_close(app)
    assert app.root.state() == "withdrawn"
    assert not app._closed
    assert icon.stops == 0
    shutdown.assert_not_called()


def test_window_x_before_readiness_closes_and_ignores_late_ready(desktop_factory):
    build, icons = desktop_factory
    app = build()
    shutdown = Mock(wraps=app.session.shutdown)
    app.session.shutdown = shutdown
    assert icons[0].started.wait(2)
    window_close(app)
    icons[0].ready()
    assert app._closed
    assert not app._tray.operational
    assert app._tray._timer is None
    assert not icons[0].visible
    shutdown.assert_called_once_with()


def test_backend_failure_keeps_visible_window_and_normal_close(desktop_factory, monkeypatch):
    build, icons = desktop_factory
    original_init = tray_module.QuickLaunchTray.__init__

    def fail_factory(_actions):
        raise RuntimeError("native tray unavailable")

    def init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        self._factory = fail_factory

    monkeypatch.setattr(tray_module.QuickLaunchTray, "__init__", init)
    app = build()
    assert icons == []
    assert not app._tray.operational
    assert "native tray unavailable" in app._tray.last_error
    assert app.root.state() != "withdrawn"
    window_close(app)
    assert app._closed


def test_backend_loss_restores_window_before_normal_close(desktop_factory):
    build, icons = desktop_factory
    app = build()
    icon = icons[0]
    icon.ready()
    pump_until(app.root, lambda: app._tray.operational)
    assert app.root.state() == "withdrawn"
    icon.visible = False
    pump_until(app.root, lambda: app._tray.last_error is not None)
    assert app.root.state() != "withdrawn"
    assert not app._closed
    assert icon.finished.is_set()
    assert not app._tray.operational
    window_close(app)
    assert app._closed


def test_worker_show_hide_quit_preserves_discard_confirmation(desktop_factory, monkeypatch):
    build, icons = desktop_factory
    app = build()
    icon = icons[0]
    icon.ready()
    pump_until(app.root, lambda: app._tray.operational)
    owner = threading.get_ident()
    original_show = app._tray.show

    def show():
        assert threading.get_ident() == owner
        original_show()

    monkeypatch.setattr(app._tray, "show", show)
    original_withdraw = app.root.withdraw

    def withdraw():
        assert threading.get_ident() == owner
        original_withdraw()

    monkeypatch.setattr(app.root, "withdraw", withdraw)
    app._dirty = True
    confirm = Mock(return_value=False)
    monkeypatch.setattr(app, "_confirm_discard", confirm)
    shutdown = Mock(wraps=app.session.shutdown)
    app.session.shutdown = shutdown

    def action(name):
        worker = threading.Thread(target=icon.actions[name])
        worker.start()
        worker.join(2)
        assert not worker.is_alive()

    action("show")
    pump_until(app.root, lambda: app.root.state() != "withdrawn")
    action("hide")
    pump_until(app.root, lambda: app.root.state() == "withdrawn")
    action("quit")
    pump_until(app.root, lambda: confirm.call_count == 1)
    assert app.root.state() != "withdrawn"
    assert not app._closed
    assert app._tray.operational
    assert icon.stops == 0
    shutdown.assert_not_called()
    confirm.return_value = True
    order = []
    original_stop = app._tray.stop

    def stop():
        order.append("tray")
        original_stop()

    def shutdown_after_stop():
        assert icon.finished.is_set()
        order.append("session")
        shutdown()

    monkeypatch.setattr(app._tray, "stop", stop)
    app.session.shutdown = shutdown_after_stop
    action("quit")
    app.root.after(2000, app.root.quit)
    app.run()
    assert app._closed
    assert order == ["tray", "session"]
    assert app._tray._timer is None
    assert not app._tray.operational
    assert icon.stops == 1
    shutdown.assert_called_once_with()
    app.close()
    assert icon.stops == 1
    assert confirm.call_count == 2


def test_auto_close_uses_cleanup_not_hide(desktop_factory):
    build, icons = desktop_factory
    app = build(auto_close=0.2)
    icon = icons[0]
    icon.ready()
    shutdown = Mock(wraps=app.session.shutdown)
    app.session.shutdown = shutdown
    app.run()
    assert app._closed
    assert icon.finished.is_set()
    assert not icon.visible
    assert app._tray._timer is None
    shutdown.assert_called_once_with()
