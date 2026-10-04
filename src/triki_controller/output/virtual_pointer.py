"""Absolute cursor for the joystick profile.

Stick 0 is the center of the focused screen. Deflection moves the pointer
away from that center and holds it there. niri honors
zwlr_virtual_pointer_v1 motion_absolute on the output given at creation.
The game stick stays a separate uinput device.
"""

from __future__ import annotations

import json
import subprocess
import threading
import time

_EXTENT = 10_000
_protocol_cache: dict[str, object] | None = None


def stick_to_screen(value: float, extent: int = _EXTENT) -> int:
    """Map a centered stick (-1..1) onto an absolute axis. 0 is the midpoint."""
    clamped = max(-1.0, min(1.0, float(value)))
    return int(round((clamped + 1.0) * 0.5 * extent))


def _focused_output_name() -> str | None:
    try:
        proc = subprocess.run(
            ["niri", "msg", "--json", "focused-output"],
            check=False,
            capture_output=True,
            text=True,
            timeout=0.4,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        name = data.get("name") or data.get("Name")
        if isinstance(name, str) and name:
            return name
    return None


def _protocol() -> dict[str, object]:
    global _protocol_cache
    if _protocol_cache is not None:
        return _protocol_cache
    from pywayland.protocol.wayland import WlOutput, WlSeat
    from pywayland.protocol_core import Argument, ArgumentType, Global, Interface, Proxy, Resource

    class ZwlrVirtualPointerV1(Interface):
        name = "zwlr_virtual_pointer_v1"
        version = 2

    class ZwlrVirtualPointerManagerV1(Interface):
        name = "zwlr_virtual_pointer_manager_v1"
        version = 2

    class ZwlrVirtualPointerV1Resource(Resource[ZwlrVirtualPointerV1]):
        interface = ZwlrVirtualPointerV1

    class ZwlrVirtualPointerManagerV1Resource(Resource[ZwlrVirtualPointerManagerV1]):
        interface = ZwlrVirtualPointerManagerV1

    class ZwlrVirtualPointerV1Proxy(Proxy[ZwlrVirtualPointerV1]):
        interface = ZwlrVirtualPointerV1

        @ZwlrVirtualPointerV1.request(
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Fixed),
            Argument(ArgumentType.Fixed),
        )
        def motion(self, time_ms: int, dx: float, dy: float) -> None:
            self._marshal(0, time_ms, dx, dy)

        @ZwlrVirtualPointerV1.request(
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
        )
        def motion_absolute(
            self, time_ms: int, x: int, y: int, x_extent: int, y_extent: int
        ) -> None:
            self._marshal(1, time_ms, x, y, x_extent, y_extent)

        @ZwlrVirtualPointerV1.request(
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
        )
        def button(self, time_ms: int, button: int, state: int) -> None:
            self._marshal(2, time_ms, button, state)

        @ZwlrVirtualPointerV1.request(
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Fixed),
        )
        def axis(self, time_ms: int, axis: int, value: float) -> None:
            self._marshal(3, time_ms, axis, value)

        @ZwlrVirtualPointerV1.request()
        def frame(self) -> None:
            self._marshal(4)

        @ZwlrVirtualPointerV1.request(Argument(ArgumentType.Uint))
        def axis_source(self, axis_source: int) -> None:
            self._marshal(5, axis_source)

        @ZwlrVirtualPointerV1.request(
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
        )
        def axis_stop(self, time_ms: int, axis: int) -> None:
            self._marshal(6, time_ms, axis)

        @ZwlrVirtualPointerV1.request(
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Uint),
            Argument(ArgumentType.Fixed),
            Argument(ArgumentType.Int),
        )
        def axis_discrete(self, time_ms: int, axis: int, value: float, discrete: int) -> None:
            self._marshal(7, time_ms, axis, value, discrete)

        @ZwlrVirtualPointerV1.request()
        def destroy(self) -> None:
            self._marshal(8)
            self._destroy()

    class ZwlrVirtualPointerManagerV1Proxy(Proxy[ZwlrVirtualPointerManagerV1]):
        interface = ZwlrVirtualPointerManagerV1

        @ZwlrVirtualPointerManagerV1.request(
            Argument(ArgumentType.Object, interface=WlSeat, nullable=True),
            Argument(ArgumentType.NewId, interface=ZwlrVirtualPointerV1),
        )
        def create_virtual_pointer(self, seat: object) -> ZwlrVirtualPointerV1Proxy:
            return self._marshal_constructor(0, ZwlrVirtualPointerV1, seat)

        @ZwlrVirtualPointerManagerV1.request()
        def destroy(self) -> None:
            self._marshal(1)
            self._destroy()

        @ZwlrVirtualPointerManagerV1.request(
            Argument(ArgumentType.Object, interface=WlSeat, nullable=True),
            Argument(ArgumentType.Object, interface=WlOutput, nullable=True),
            Argument(ArgumentType.NewId, interface=ZwlrVirtualPointerV1),
        )
        def create_virtual_pointer_with_output(
            self, seat: object, output: object
        ) -> ZwlrVirtualPointerV1Proxy:
            return self._marshal_constructor(2, ZwlrVirtualPointerV1, seat, output)

    class ZwlrVirtualPointerV1Global(Global[ZwlrVirtualPointerV1]):
        interface = ZwlrVirtualPointerV1

    class ZwlrVirtualPointerManagerV1Global(Global[ZwlrVirtualPointerManagerV1]):
        interface = ZwlrVirtualPointerManagerV1

    ZwlrVirtualPointerV1._gen_c()
    ZwlrVirtualPointerV1.proxy_class = ZwlrVirtualPointerV1Proxy
    ZwlrVirtualPointerV1.resource_class = ZwlrVirtualPointerV1Resource
    ZwlrVirtualPointerV1.global_class = ZwlrVirtualPointerV1Global
    ZwlrVirtualPointerManagerV1._gen_c()
    ZwlrVirtualPointerManagerV1.proxy_class = ZwlrVirtualPointerManagerV1Proxy
    ZwlrVirtualPointerManagerV1.resource_class = ZwlrVirtualPointerManagerV1Resource
    ZwlrVirtualPointerManagerV1.global_class = ZwlrVirtualPointerManagerV1Global
    _protocol_cache = {
        "pointer": ZwlrVirtualPointerV1,
        "manager": ZwlrVirtualPointerManagerV1,
        "output": WlOutput,
    }
    return _protocol_cache


class AbsoluteCursor:
    """Places the Wayland pointer from a centered stick. Soft-fails when closed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._display = None
        self._pointer = None
        self._manager = None
        self.output_name: str | None = None

    def open(self) -> str | None:
        """None when the pointer is ready. Otherwise a short reason."""
        with self._lock:
            try:
                from pywayland.client import Display
            except ImportError:
                return "kursor absolutny wymaga pywayland"
            try:
                proto = _protocol()
                display = Display()
                display.connect()
            except Exception as exc:
                return f"kursor absolutny: brak Wayland ({exc})"
            manager_iface = proto["manager"]
            output_iface = proto["output"]
            found: dict[str, object] = {}
            outputs: list[dict[str, object]] = []

            def on_global(registry: object, name: int, interface: str, version: int) -> None:
                if interface == "zwlr_virtual_pointer_manager_v1":
                    found["manager"] = registry.bind(name, manager_iface, min(int(version), 2))  # type: ignore[attr-defined]
                elif interface == "wl_output":
                    proxy = registry.bind(name, output_iface, min(int(version), 4))  # type: ignore[attr-defined]
                    info: dict[str, object] = {"proxy": proxy, "name": None}

                    def on_name(_proxy: object, output_name: str, info: dict[str, object] = info) -> None:
                        info["name"] = output_name

                    proxy.dispatcher["name"] = on_name  # type: ignore[attr-defined]
                    outputs.append(info)

            try:
                registry = display.get_registry()
                registry.dispatcher["global"] = on_global
                display.roundtrip()
                display.roundtrip()
            except Exception as exc:
                display.disconnect()
                return f"kursor absolutny: rejestr Wayland ({exc})"
            manager = found.get("manager")
            if manager is None:
                display.disconnect()
                return "kursor absolutny: kompozytor nie ma zwlr_virtual_pointer"
            focused = _focused_output_name()
            chosen = None
            for info in outputs:
                if focused and info.get("name") == focused:
                    chosen = info
                    break
            if chosen is None and outputs:
                chosen = outputs[0]
            try:
                if chosen is None:
                    pointer = manager.create_virtual_pointer(None)  # type: ignore[attr-defined]
                else:
                    pointer = manager.create_virtual_pointer_with_output(None, chosen["proxy"])  # type: ignore[attr-defined]
                display.flush()
            except Exception as exc:
                display.disconnect()
                return f"kursor absolutny: nie utworzono wskaźnika ({exc})"
            self._display = display
            self._pointer = pointer
            self._manager = manager
            self.output_name = None if chosen is None else str(chosen.get("name") or "")
            return None

    def place(self, stick_x: float, stick_y: float) -> None:
        with self._lock:
            pointer = self._pointer
            display = self._display
            if pointer is None or display is None:
                return
            now = int(time.monotonic() * 1000) & 0xFFFFFFFF
            pointer.motion_absolute(
                now,
                stick_to_screen(stick_x),
                stick_to_screen(stick_y),
                _EXTENT,
                _EXTENT,
            )
            pointer.frame()
            display.flush()

    def close(self) -> None:
        with self._lock:
            pointer = self._pointer
            manager = self._manager
            display = self._display
            self._pointer = None
            self._manager = None
            self._display = None
            if display is None:
                return
            try:
                if pointer is not None:
                    pointer.destroy()
                if manager is not None:
                    manager.destroy()
                display.flush()
            except Exception:
                pass
            try:
                display.disconnect()
            except Exception:
                pass
