"""Transport adapters — fake default; Bleak behind optional ``[ble]`` extra."""

from triki_controller.transport.base import Transport
from triki_controller.transport.fake import FakeTransport, SyntheticStreamSpec

__all__ = ["Transport", "FakeTransport", "SyntheticStreamSpec", "BleTransport", "BleTransportConfig"]


def __getattr__(name: str) -> object:
    if name in ("BleTransport", "BleTransportConfig"):
        from triki_controller.transport.ble import BleTransport, BleTransportConfig

        return {"BleTransport": BleTransport, "BleTransportConfig": BleTransportConfig}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
