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
                                "kCGEventRightMouseUp"),
               "mouse_middle": ("kCGMouseButtonCenter", "kCGEventOtherMouseDown", "kCGEventOtherMouseUp")}

    def __init__(self, *, quartz=None):
        self._q = quartz
        self._injected = quartz is not None
        self._held = set()

    def open(self):
        if self._injected:
            if self._q is None or not self._q.CGPreflightPostEventAccess():
                raise RuntimeError("Accessibility permission denied; input not opened")
            return
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

    def key(self, name, down):
        if self._q is None:
            raise RuntimeError("Quartz input is not open")
        # HIToolbox virtual key positions, not Unicode text injection.
        codes = dict(zip('abcdefghijklmnopqrstuvwxyz',
            (0, 11, 8, 2, 14, 3, 5, 4, 34, 38, 40, 37, 46, 45, 31, 35,
             12, 15, 1, 17, 32, 9, 13, 7, 16, 6)))
        codes.update(dict(zip('0123456789', (29, 18, 19, 20, 21, 23, 22, 26, 28, 25))))
        codes.update({'up': 126, 'down': 125, 'left': 123, 'right': 124,
                      'space': 49, 'enter': 36, 'escape': 53, 'shift': 56,
                      'ctrl': 59, 'alt': 58, 'tab': 48, 'backspace': 51})
        code = codes.get(name[4:]) if name.startswith('key_') else None
        if code is None:
            raise ValueError(f'unsupported Quartz key {name!r}')
        self._post(self._q.CGEventCreateKeyboardEvent(None, code, bool(down)))
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
        elif "mouse_middle" in self._held:
            kind, button = q.kCGEventOtherMouseDragged, q.kCGMouseButtonCenter
        else:
            kind, button = q.kCGEventMouseMoved, q.kCGMouseButtonLeft
        self._post(q.CGEventCreateMouseEvent(None, kind, (point.x + x, point.y + y), button))

    def close(self):
        # Backend owns releasing buttons. Preserve this adapter for retry if release failed.
        if self._held:
            raise RuntimeError("cannot close Quartz while mouse buttons remain held")
        self._q = None
