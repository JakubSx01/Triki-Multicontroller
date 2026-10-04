"""SendInput mouse/transport adapter, stdlib only, lazy Windows loading.

SendInput is subject to Windows UIPI. A zero/short count is a failure, not
proof of delivery. Global media keys are not pinned to the audio player.
Fixed Win32 widths keep ABI tests meaningful even on non-Windows hosts.
"""
from __future__ import annotations

import ctypes
import math
import sys
import threading

DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', LONG), ('dy', LONG), ('mouseData', DWORD),
                ('dwFlags', DWORD), ('time', DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', WORD), ('wScan', WORD), ('dwFlags', DWORD),
                ('time', DWORD), ('dwExtraInfo', ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', DWORD), ('wParamL', WORD), ('wParamH', WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', DWORD), ('data', _INPUTUNION)]


class WindowsInput:
    def __init__(self, *, send_input=None):
        self._lock = threading.RLock()
        self._buttons = set()
        self._keys = set()
        self._closed = False
        if send_input is None:
            if sys.platform != 'win32':
                raise RuntimeError('SendInput is available only on Windows')
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            native = user32.SendInput
            native.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
            native.restype = ctypes.c_uint
            def send_input(items):
                array = (INPUT * len(items))(*items)
                ctypes.set_last_error(0)
                sent = int(native(len(items), array, ctypes.sizeof(INPUT)))
                if sent != len(items):
                    raise OSError(ctypes.get_last_error(), 'SendInput failed (possibly UIPI/integrity level)')
                return sent
        self._send_input = send_input

    def _send(self, item):
        if self._closed:
            raise RuntimeError('Windows input adapter is closed')
        count = self._send_input((item,))
        if count != 1:
            raise RuntimeError(f'SendInput inserted {count}/1 events (possibly UIPI)')

    def relative(self, x, y):
        with self._lock:
            x, y = int(x), int(y)
            if not (-2147483648 <= x <= 2147483647 and -2147483648 <= y <= 2147483647):
                raise ValueError('relative pointer outside LONG range')
            self._send(INPUT(type=0, data=_INPUTUNION(mi=MOUSEINPUT(dx=x, dy=y, dwFlags=1))))

    def absolute(self, x, y):
        """Normalized [-1,1] coordinates on the full Windows virtual desktop."""
        with self._lock:
            x, y = float(x), float(y)
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError('non-finite pointer position')
            px = round((max(-1.0, min(1.0, x)) + 1) * 32767.5)
            py = round((max(-1.0, min(1.0, y)) + 1) * 32767.5)
            self._send(INPUT(type=0, data=_INPUTUNION(mi=MOUSEINPUT(dx=px, dy=py, dwFlags=0xc001))))

    def button(self, name, down):
        with self._lock:
            flags = {'mouse_left': (2, 4), 'mouse_right': (8, 16), 'mouse_middle': (32, 64)}.get(name)
            if flags is None:
                raise ValueError(f'unsupported Windows button {name!r}')
            self._send(INPUT(type=0, data=_INPUTUNION(mi=MOUSEINPUT(dwFlags=flags[0 if down else 1]))))
            if down:
                self._buttons.add(name)
            else:
                self._buttons.discard(name)

    def _key(self, vk, down):
        self._send(INPUT(type=1, data=_INPUTUNION(ki=KEYBDINPUT(wVk=vk, dwFlags=(1 if vk in {0x25, 0x26, 0x27, 0x28} else 0) | (0 if down else 2)))))
        if down:
            self._keys.add(vk)
        else:
            self._keys.discard(vk)

    def key(self, name, down):
        with self._lock:
            codes = {'key_' + c: ord(c.upper()) for c in 'abcdefghijklmnopqrstuvwxyz0123456789'}
            codes.update({'key_' + n: v for n, v in {
                'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
                'space': 0x20, 'enter': 0x0d, 'escape': 0x1b, 'shift': 0x10,
                'ctrl': 0x11, 'alt': 0x12, 'tab': 0x09, 'backspace': 0x08}.items()})
            if name not in codes:
                raise ValueError(f'unsupported Windows key {name!r}')
            self._key(codes[name], down)

    def transport(self, name):
        with self._lock:
            vk = {'play_pause': 0xb3, 'next_track': 0xb0, 'previous_track': 0xb1}.get(name)
            if vk is None:
                # Never emit VK_VOLUME_*: player failures must not hit master.
                raise ValueError(f'unsupported transport key {name!r}')
            self._key(vk, True)
            self._key(vk, False)

    def neutralize(self):
        with self._lock:
            errors = []
            for vk in sorted(self._keys):
                try:
                    self._key(vk, False)
                except Exception as exc:
                    errors.append(str(exc))
            for name in sorted(self._buttons):
                try:
                    self.button(name, False)
                except Exception as exc:
                    errors.append(str(exc))
            if errors:
                raise RuntimeError('; '.join(errors))

    def close(self):
        with self._lock:
            if not self._closed:
                self.neutralize()
                self._closed = True
