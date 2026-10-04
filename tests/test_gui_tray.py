"""Public tray lifecycle tested without a display or optional dependencies."""
from __future__ import annotations

import threading
import unittest
from unittest.mock import patch
from typing import Any

from triki_controller.gui import tray as tray_module

from triki_controller.gui.tray import QuickLaunchTray


class Root:
    def __init__(self):
        self.owner = threading.get_ident()
        self.pending = {}
        self.events = []
        self.serial = 0

    def record(self, event):
        assert threading.get_ident() == self.owner, "Tk accessed from tray thread"
        self.events.append(event)

    def after(self, delay, callback):
        self.record("after")
        self.serial += 1
        self.pending[self.serial] = callback
        return self.serial

    def after_cancel(self, token):
        self.record("cancel")
        self.pending.pop(token, None)

    def pump(self):
        token = next(iter(self.pending))
        self.pending.pop(token)()

    def withdraw(self):
        self.record("hide")

    def deiconify(self):
        self.record("show")

    def lift(self):
        self.record("lift")


class Icon:
    def __init__(self):
        self.visible = False
        self.setup: Any = None
        self._appindicator: Any = None
        self.stops = 0
        self.started = threading.Event()
        self.finished = threading.Event()

    def run(self, setup):
        self.run_detached(setup)
        self.finished.wait(10)

    def run_detached(self, setup):
        self.setup = setup
        self.started.set()

    def ready(self):
        assert self.started.wait(2), "Backend did not start"
        assert self.setup is not None
        thread = threading.Thread(target=lambda: self.setup(self))
        thread.start()
        thread.join()

    def stop(self):
        if self.finished.is_set():
            return
        self.stops += 1
        self.visible = False
        self.finished.set()


class TrayTests(unittest.TestCase):
    def test_quick_window_hides_only_after_backend_ready_on_tk_thread(self):
        root = Root()
        icon = Icon()
        tray = QuickLaunchTray(root, on_quit=lambda: None,
                               icon_factory=lambda actions: icon)
        self.assertTrue(tray.start())
        self.assertNotIn("hide", root.events)
        self.assertFalse(tray.operational)
        icon.ready()
        self.assertNotIn("hide", root.events)
        root.pump()
        self.assertTrue(tray.operational)
        self.assertEqual(root.events.count("hide"), 1)
        tray.stop()

    def make_tray(self, **kwargs):
        root, icon, actions = Root(), Icon(), {}
        def factory(callbacks):
            actions.update(callbacks)
            return icon
        tray = QuickLaunchTray(root, on_quit=kwargs.pop("on_quit", lambda: None),
                               icon_factory=factory, **kwargs)
        self.addCleanup(tray.stop)
        return root, icon, actions, tray

    def test_hide_is_refused_until_ready(self):
        root, icon, actions, tray = self.make_tray()
        self.assertFalse(tray.hide())
        self.assertNotIn("hide", root.events)
        tray.start()
        self.assertFalse(tray.hide())

    def test_worker_menu_actions_only_touch_tk_during_poll(self):
        root, icon, actions, tray = self.make_tray()
        tray.start()
        icon.ready()
        root.pump()
        for action, expected in (("show", "show"), ("hide", "hide")):
            before = list(root.events)
            worker = threading.Thread(target=lambda: actions[action](icon, None))
            worker.start()
            worker.join()
            self.assertEqual(root.events, before)
            root.pump()
            self.assertIn(expected, root.events[len(before):])

    def test_quit_delegates_existing_cleanup_on_owner_thread(self):
        calls = []
        def close():
            self.assertEqual(threading.get_ident(), root.owner)
            calls.append("session shutdown")
            tray.stop()
        root, icon, actions, tray = self.make_tray(on_quit=close)
        tray.start()
        icon.ready()
        root.pump()
        actions["quit"]()
        root.pump()
        self.assertEqual(calls, ["session shutdown"])
        self.assertEqual(icon.stops, 1)
        self.assertFalse(tray.operational)
        self.assertEqual(root.pending, {})

    def test_rejected_quit_keeps_tray_and_window_visible(self):
        root, icon, actions, tray = self.make_tray()
        tray.start()
        icon.ready()
        root.pump()
        actions["quit"]()
        root.pump()
        self.assertTrue(tray.operational)
        self.assertEqual(icon.stops, 0)
        self.assertIn("show", root.events)
        self.assertTrue(root.pending)

    def test_missing_optional_dependency_keeps_visible_window(self):
        root, errors = Root(), []
        with patch.object(tray_module.importlib, "import_module", side_effect=ImportError("pystray missing")):
            tray = QuickLaunchTray(root, on_quit=lambda: None, on_error=errors.append)
            self.assertFalse(tray.start())
        self.assertFalse(tray.operational)
        self.assertNotIn("hide", root.events)
        self.assertIn("show", root.events)
        self.assertEqual(errors, [tray.last_error])
        self.assertIn("pystray missing", tray.last_error or "")
        self.assertEqual(root.pending, {})

    def test_detached_start_failure_cleans_up(self):
        root, icon, actions, tray = self.make_tray()
        with patch.object(tray_module.sys, "platform", "darwin"), patch.object(icon, "run_detached", side_effect=RuntimeError("backend error")):
            self.assertFalse(tray.start())
        self.assertEqual(icon.stops, 1)
        self.assertIn("show", root.events)
        self.assertNotIn("hide", root.events)
        self.assertEqual(root.pending, {})

    def test_startup_timeout_never_hides_window(self):
        root, icon, actions, tray = self.make_tray(startup_timeout_s=0)
        self.assertTrue(tray.start())
        root.pump()
        self.assertIn("timed out", tray.last_error or "")
        self.assertEqual(icon.stops, 1)
        self.assertNotIn("hide", root.events)
        self.assertEqual(root.pending, {})

    def test_setup_failure_is_reported_on_tk_thread(self):
        root, icon = Root(), Icon()
        with patch.object(tray_module.sys, "platform", "linux"), patch.object(tray_module, "_create_icon", return_value=icon):
            tray = QuickLaunchTray(root, on_quit=lambda: None)
            self.addCleanup(tray.stop)
            tray.start()
        with patch.object(tray_module, "_linux_tray_host", return_value=False):
            icon.ready()
        self.assertNotIn("show", root.events)
        root.pump()
        self.assertIn("No AppIndicator tray host", tray.last_error or "")
        self.assertNotIn("hide", root.events)
        self.assertEqual(icon.stops, 1)

    def test_linux_waits_for_native_activation_not_python_visibility_flag(self):
        from types import SimpleNamespace
        for active in (True, False):
            with self.subTest(active=active):
                root, icon = Root(), Icon()
                icon._appindicator = SimpleNamespace(get_status=lambda: 1 if active else 0)
                scheduled, callbacks = threading.Event(), []
                def idle_add(callback, argument):
                    callbacks.append((callback, argument))
                    scheduled.set()
                glib = SimpleNamespace(idle_add=idle_add)
                backend = SimpleNamespace(AppIndicator=SimpleNamespace(IndicatorStatus=SimpleNamespace(ACTIVE=1)))
                modules = {"gi.repository.GLib": glib, "pystray._appindicator": backend}
                with patch.object(tray_module.sys, "platform", "linux"), patch.object(tray_module, "_create_icon", return_value=icon), patch.object(tray_module, "_linux_tray_host", return_value=True), patch.object(tray_module.importlib, "import_module", side_effect=modules.__getitem__):
                    tray = QuickLaunchTray(root, on_quit=lambda: None)
                    self.assertTrue(tray.start())
                    self.assertTrue(icon.started.wait(2))
                    setup = icon.setup
                    assert setup is not None
                    worker = threading.Thread(target=lambda: setup(icon))
                    worker.start()
                    try:
                        self.assertTrue(scheduled.wait(2))
                        root.pump()
                        self.assertTrue(icon.visible)
                        self.assertFalse(tray.operational)
                        self.assertNotIn("hide", root.events)
                        callback, argument = callbacks[0]
                        native = threading.Thread(target=lambda: callback(argument))
                        native.start()
                        native.join()
                        root.pump()
                        self.assertEqual(tray.operational, active)
                        if active:
                            self.assertIn("hide", root.events)
                        else:
                            self.assertNotIn("hide", root.events)
                            self.assertIn("did not become active", tray.last_error or "")
                    finally:
                        tray.stop()
                        worker.join(2)
                        self.assertFalse(worker.is_alive())

    def test_runtime_icon_loss_restores_window(self):
        root, icon, actions, tray = self.make_tray()
        tray.start()
        icon.ready()
        root.pump()
        icon.visible = False
        root.pump()
        self.assertIn("no longer visible", tray.last_error or "")
        self.assertIn("show", root.events)
        self.assertEqual(icon.stops, 1)
        self.assertFalse(tray.hide())

    def test_stop_is_idempotent_and_ignores_late_callbacks(self):
        root, icon, actions, tray = self.make_tray()
        tray.start()
        self.assertTrue(icon.started.wait(2))
        tray.stop()
        tray.stop()
        icon.ready()
        actions["show"]()
        self.assertEqual(icon.stops, 1)
        self.assertFalse(icon.visible)
        self.assertFalse(tray.start())
        self.assertEqual(root.pending, {})
        self.assertNotIn("hide", root.events)

    def test_stop_before_start_and_double_start_are_safe(self):
        root, icon, actions, tray = self.make_tray()
        tray.stop()
        self.assertFalse(tray.start())
        self.assertEqual(icon.stops, 0)
        root, icon, actions, tray = self.make_tray()
        self.assertTrue(tray.start())
        self.assertTrue(tray.start())
        self.assertEqual(len(root.pending), 1)

    def test_visible_start_option_preserves_window(self):
        root, icon, actions, tray = self.make_tray(hide_on_ready=False)
        tray.start()
        icon.ready()
        root.pump()
        self.assertTrue(tray.operational)
        self.assertNotIn("hide", root.events)
        self.assertTrue(tray.hide())

    def test_backend_stop_error_does_not_block_cleanup(self):
        root, icon, actions, tray = self.make_tray()
        tray.start()
        with patch.object(icon, "stop", side_effect=RuntimeError("stop failed")):
            tray.stop()
        self.assertEqual(root.pending, {})
        self.assertFalse(tray.operational)

    def test_background_backend_failure_keeps_window_visible(self):
        root, icon, actions, tray = self.make_tray()
        completed = threading.Event()
        def broken_run(setup):
            completed.set()
            raise RuntimeError("native event loop failed")
        with patch.object(icon, "run", side_effect=broken_run):
            self.assertTrue(tray.start())
            self.assertTrue(completed.wait(2))
        # Allow the background exception to reach owner-thread polling.
        import time
        deadline = time.monotonic() + 2
        while tray.last_error is None and time.monotonic() < deadline:
            root.pump()
            time.sleep(0.001)
        self.assertIn("native event loop failed", tray.last_error or "")
        self.assertNotIn("hide", root.events)
        self.assertIn("show", root.events)

    def test_macos_detached_integration_starts_on_tk_thread(self):
        root, icon, actions, tray = self.make_tray()
        detached = icon.run_detached
        def start_detached(setup):
            root.record("detached")
            detached(setup)
        with patch.object(tray_module.sys, "platform", "darwin"), patch.object(icon, "run_detached", side_effect=start_detached):
            self.assertTrue(tray.start())
        self.assertIn("detached", root.events)
        icon.ready()
        root.pump()
        self.assertTrue(tray.operational)

    def test_wrong_thread_cannot_run_lifecycle(self):
        root, icon, actions, tray = self.make_tray()
        errors = []
        def worker():
            try:
                tray.start()
            except RuntimeError as exc:
                errors.append(str(exc))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(errors, ["Tray lifecycle must run on the Tk owner thread"])
        self.assertEqual(root.events, [])

    def test_real_tk_mainloop_processes_worker_ready(self):
        try:
            import tkinter as tk
        except ImportError as exc:
            self.skipTest(f"Tk unavailable: {exc}")
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"Display unavailable: {exc}")
        icon = Icon()
        tray = QuickLaunchTray(root, on_quit=lambda: None,
                               icon_factory=lambda actions: icon)
        try:
            tray.start()
            icon.ready()
            root.after(120, root.quit)
            root.mainloop()
            self.assertTrue(tray.operational)
            self.assertEqual(root.state(), "withdrawn")
            tray.show()
            self.assertEqual(root.state(), "normal")
        finally:
            tray.stop()
            root.destroy()


class HostTests(unittest.TestCase):
    def test_watcher_owner_is_required(self):
        from types import SimpleNamespace
        with patch.object(tray_module.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="(true,)\n")):
            self.assertTrue(tray_module._linux_tray_host())
        for stdout in ("(false,)\n", "error"):
            with patch.object(tray_module.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=stdout)):
                self.assertFalse(tray_module._linux_tray_host())
        with patch.object(tray_module.subprocess, "run", side_effect=FileNotFoundError):
            self.assertFalse(tray_module._linux_tray_host())


if __name__ == "__main__":
    unittest.main()
