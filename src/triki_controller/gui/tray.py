"""Optional quick-launch tray shell; never touches profiles, output or settings.

Construct/start/stop on the Tk owner thread, before mainloop. Backend callbacks
only enqueue messages: even Tk.after must not be called from a tray thread.
Linux deliberately requires AppIndicator and a StatusNotifierWatcher, rather
than trusting pystray's GTK/Xorg visibility flag on desktops without a tray.
"""
from __future__ import annotations

import importlib
import logging
import queue
import subprocess
import sys
import threading
import time
from typing import Any, Callable

_LOG = logging.getLogger(__name__)


def _linux_tray_host() -> bool:
    """Fail closed when a supported tray host cannot be confirmed."""
    try:
        result = subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
             "--object-path", "/org/freedesktop/DBus", "--method",
             "org.freedesktop.DBus.NameHasOwner", "org.kde.StatusNotifierWatcher"],
            capture_output=True, text=True, timeout=1, check=False,
        )
        return result.returncode == 0 and result.stdout.strip() == "(true,)"
    except (OSError, subprocess.TimeoutExpired):
        return False


def _create_icon(actions: dict[str, Callable[..., None]]) -> Any:
    # Importing pystray itself can fail without DISPLAY or platform libraries.
    # Keep that import outside module scope so ordinary GUI/headless use works.
    pystray = importlib.import_module("pystray")
    if sys.platform.startswith("linux"):
        if pystray.Icon.__module__ != "pystray._appindicator":
            raise RuntimeError("Linux tray requires AppIndicator; GTK/Xorg cannot guarantee visibility")
    if not pystray.Icon.HAS_MENU:
        raise RuntimeError("Tray backend does not support Show/Hide/Quit menus")
    from PIL import Image, ImageDraw

    from triki_controller.gui.app_icon import icon_file

    emblem = icon_file("png")
    if emblem is not None:
        image = Image.open(emblem).convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
    else:
        image = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((4, 4, 60, 60), radius=12, fill="#2F6FED")
        draw.line((17, 21, 47, 21), fill="white", width=7)
        draw.line((32, 21, 32, 47), fill="white", width=7)
    options: dict[str, Any] = {}
    if sys.platform == "darwin":
        # Tk has already created its Cocoa application by the time start runs.
        from AppKit import NSApplication
        options["darwin_nsapplication"] = NSApplication.sharedApplication()
    return pystray.Icon(
        "triki-controller", image, "Triki Controller",
        **options,
        menu=pystray.Menu(
            pystray.MenuItem("Pokaż okno", actions["show"], default=True),
            pystray.MenuItem("Ukryj okno", actions["hide"]),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Zakończ", actions["quit"]),
        ),
    )


class QuickLaunchTray:
    """Window-only lifecycle adapter with a testable optional icon factory.

    start() means initialization was requested, not that it is operational.
    Only the backend setup acknowledgement makes hide() safe. Quit delegates
    to the existing application close callback, preserving its discard prompt
    and session cleanup. That callback must call stop() after accepting close.
    stop() is idempotent, cancels Tk polling, and removes the tray icon.
    """

    def __init__(
        self, root: Any, *, on_quit: Callable[[], None],
        on_error: Callable[[str], None] | None = None,
        icon_factory: Callable[[dict[str, Callable[..., None]]], Any] | None = None,
        hide_on_ready: bool = True, startup_timeout_s: float = 5.0,
    ) -> None:
        self.root = root
        self._on_quit = on_quit
        self._on_error = on_error
        self._factory = icon_factory or _create_icon
        self._check_host = icon_factory is None and sys.platform.startswith("linux")
        self._hide_on_ready = hide_on_ready
        self._timeout = startup_timeout_s
        self._owner = threading.get_ident()
        self._messages: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self._icon: Any = None
        self._timer: Any = None
        self._started = False
        self._stopped = threading.Event()
        self._backend_lock = threading.Lock()
        self._hidden = False
        self.operational = False
        self.last_error: str | None = None

    def _assert_owner(self) -> None:
        if threading.get_ident() != self._owner:
            raise RuntimeError("Tray lifecycle must run on the Tk owner thread")

    def _enqueue(self, action: str) -> Callable[..., None]:
        def callback(*_args: Any) -> None:
            if not self._stopped.is_set():
                self._messages.put((action, ""))
        return callback

    def start(self) -> bool:
        self._assert_owner()
        if self._stopped.is_set():
            return False
        if self._started:
            return True
        self._started = True
        self._deadline = time.monotonic() + self._timeout
        try:
            self._icon = self._factory({key: self._enqueue(key) for key in ("show", "hide", "quit")})
            self._timer = self.root.after(50, self._poll)
            # Tk does not drive GLib: Linux/Windows need a dedicated backend
            # loop. macOS alone must integrate with the main Cocoa runloop.
            if sys.platform == "darwin":
                self._icon.run_detached(setup=self._setup)
            else:
                threading.Thread(target=self._run_icon, name="triki-tray", daemon=True).start()
        except Exception as exc:
            self._fail(str(exc))
            return False
        return True

    def _run_icon(self) -> None:
        if self._stopped.is_set():
            return
        try:
            self._icon.run(setup=self._setup)
            if not self._stopped.is_set():
                self._messages.put(("error", "Tray event loop stopped"))
        except Exception as exc:
            self._messages.put(("error", str(exc)))

    def _setup(self, icon: Any) -> None:
        try:
            if self._stopped.is_set():
                icon.stop()
                return
            if self._check_host and not _linux_tray_host():
                raise RuntimeError("No AppIndicator tray host (or gdbus unavailable)")
            with self._backend_lock:
                if self._stopped.is_set():
                    return
                icon.visible = True
                if self._check_host:
                    # AppIndicator's visible setter schedules GLib work. Its
                    # Python flag alone is not an operational acknowledgement.
                    GLib = importlib.import_module("gi.repository.GLib")
                    GLib.idle_add(self._confirm_linux_ready, icon)
                else:
                    self._messages.put(("ready", ""))
            # Watch host loss off the Tk thread. stop() wakes this immediately,
            # avoiding pystray's setup-thread join timeout during cleanup.
            while self._check_host and not self._stopped.wait(2):
                if not _linux_tray_host():
                    self._messages.put(("error", "Tray host disappeared"))
                    return
        except Exception as exc:
            self._messages.put(("error", str(exc)))

    def _confirm_linux_ready(self, icon: Any) -> bool:
        # Executes after pystray's queued _show on the GLib loop. This adapter
        # intentionally checks the native status, not just Icon.visible.
        if self._stopped.is_set():
            return False
        try:
            backend = importlib.import_module("pystray._appindicator")
            active = backend.AppIndicator.IndicatorStatus.ACTIVE
            if icon._appindicator.get_status() != active:
                raise RuntimeError("AppIndicator did not become active")
            self._messages.put(("ready", ""))
        except Exception as exc:
            self._messages.put(("error", str(exc)))
        return False

    def _poll(self) -> None:
        self._assert_owner()
        self._timer = None
        if self._stopped.is_set():
            return
        try:
            while not self._messages.empty() and not self._stopped.is_set():
                action, detail = self._messages.get_nowait()
                if action == "error":
                    self._fail(detail)
                elif action == "ready":
                    if not self._icon.visible:
                        raise RuntimeError("Tray icon did not become visible")
                    self.operational = True
                    if self._hide_on_ready:
                        self.hide()
                elif action == "show":
                    self.show()
                elif action == "hide":
                    self.hide()
                elif action == "quit":
                    # Do not stop before the app accepts its close prompt.
                    self.show()
                    self._on_quit()
            if not self._stopped.is_set():
                if not self.operational and time.monotonic() >= self._deadline:
                    self._fail("Tray startup timed out")
                elif self.operational and not self._icon.visible:
                    self._fail("Tray icon is no longer visible")
        except Exception as exc:
            self._fail(str(exc))
        finally:
            if not self._stopped.is_set():
                self._timer = self.root.after(50, self._poll)

    def show(self) -> None:
        self._assert_owner()
        self.root.deiconify()
        self.root.lift()
        self._hidden = False

    def hide(self) -> bool:
        self._assert_owner()
        if not self.operational or self._stopped.is_set():
            return False
        self.root.withdraw()
        self._hidden = True
        return True

    def _fail(self, detail: str) -> None:
        self.last_error = f"Zasobnik niedostępny; okno pozostaje widoczne: {detail}"
        self.stop()
        try:
            self.show()
        except Exception:
            _LOG.debug("Cannot restore closed Tk window", exc_info=True)
        _LOG.warning("%s", self.last_error)
        if self._on_error is not None:
            try:
                self._on_error(self.last_error)
            except Exception:
                _LOG.exception("Tray error handler failed")

    def stop(self) -> None:
        self._assert_owner()
        with self._backend_lock:
            if self._stopped.is_set():
                return
            self._stopped.set()
        self.operational = False
        if self._timer is not None:
            try:
                self.root.after_cancel(self._timer)
            except Exception:
                _LOG.debug("Cannot cancel tray timer on closed Tk window", exc_info=True)
            self._timer = None
        if self._icon is not None:
            try:
                self._icon.visible = False
            except Exception:
                _LOG.debug("Cannot hide tray icon during cleanup", exc_info=True)
            try:
                self._icon.stop()
            except Exception:
                _LOG.warning("Tray backend cleanup failed", exc_info=True)
