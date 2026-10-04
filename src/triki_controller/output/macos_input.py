"""Optional native Quartz pointer; frameworks loaded only on live mouse open.

Requires pyobjc-framework-Quartz and macOS Accessibility permission for the
host app/terminal. No virtual HID joystick or guessed media-key event codes.
"""
from __future__ import annotations
import sys


class QuartzMouseInput:
    BUTTONS = {"mouse_left": ("kCGMouseButtonLeft", "kCGEventLeftMouseDown",
                               "kCGEventLeftMouseUp"),
               "mouse_right": ("kCGMouseButtonRight", "kCGEventRightMouseDown",
                                "kCGEventRightMouseUp")}

    def __init__(self):
        self._q = None
        self._held = set()

    def open(self):
        if sys.platform != "darwin":
            raise RuntimeError("Quartz pointer requires macOS")
        try:
            import Quartz
        except ImportError as exc:
            raise RuntimeError("mouse output needs pyobjc-framework-Quartz") from exc
        if not Quartz.CGPreflightPostEventAccess():
            raise RuntimeError("mouse output denied: grant Accessibility to the host app/terminal "
                               "in macOS Privacy & Security; no automatic permission prompt")
        self._q = Quartz

    def _post(self, event):
        if self._q is None:
            raise RuntimeError("Quartz mouse is not open")
        if not self._q.CGPreflightPostEventAccess():
            raise RuntimeError("Accessibility permission revoked; mouse event not posted")
        if event is None:
            raise RuntimeError("Quartz failed to create mouse event")
        self._q.CGEventPost(self._q.kCGHIDEventTap, event)
        # Quartz has no delivery acknowledgment; do not claim target-app consumption.

    def button(self, name, down):
        if self._q is None:
            raise RuntimeError("Quartz mouse is not open")
        if name not in self.BUTTONS:
            raise RuntimeError(f"unsupported mouse button/key {name!r}")
        q = self._q
        button, press, release = self.BUTTONS[name]
        probe = q.CGEventCreate(None)
        if probe is None:
            raise RuntimeError("Quartz cannot read pointer location")
        point = q.CGEventGetLocation(probe)
        event = q.CGEventCreateMouseEvent(None, getattr(q, press if down else release),
                                        point, getattr(q, button))
        self._post(event)
        if down:
            self._held.add(name)
        else:
            self._held.discard(name)

    def move(self, x, y):
        if self._q is None:
            raise RuntimeError("Quartz mouse is not open")
        q = self._q
        probe = q.CGEventCreate(None)
        if probe is None:
            raise RuntimeError("Quartz cannot read pointer location")
        point = q.CGEventGetLocation(probe)
        if "mouse_left" in self._held:
            kind, button = q.kCGEventLeftMouseDragged, q.kCGMouseButtonLeft
        elif "mouse_right" in self._held:
            kind, button = q.kCGEventRightMouseDragged, q.kCGMouseButtonRight
        else:
            kind, button = q.kCGEventMouseMoved, q.kCGMouseButtonLeft
        self._post(q.CGEventCreateMouseEvent(None, kind, (point.x + x, point.y + y), button))

    def close(self):
        # Backend owns releasing buttons. Preserve this adapter for retry if release failed.
        if self._held:
            raise RuntimeError("cannot close Quartz while mouse buttons remain held")
        self._q = None
