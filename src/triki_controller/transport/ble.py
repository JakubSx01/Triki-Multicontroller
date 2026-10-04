"""Provisional Bleak transport for CAP001 via Nordic UART Service.

Derived from TrikiScope ``trikiscope/ble.py`` / ``config.py`` (MIT License).
Copyright (c) 2026 Mateusz "Maku" Mączewski — see THIRD_PARTY_NOTICES.md.

This adapter is **reference-hypothesis only** — not HOM-27 measured evidence.
No TUI, games, LED control, or profile logic lives here.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import AsyncIterator, Callable

from triki_controller.core.models import (
    SCHEMA_VERSION,
    ConnectionEvent,
    ConnectionState,
    Notification,
)
from triki_controller.protocol.cap001_hypothesis import (
    NUS_RX_CHAR_UUID,
    NUS_TX_CHAR_UUID,
)

# TrikiScope default start command (Zappka-app derived) — provisional.
DEFAULT_START_COMMAND = bytes.fromhex("201000D007680003")
DEFAULT_DEVICE_NAME_NEEDLE = "Triki"
DEFAULT_SCAN_TIMEOUT_SECONDS = 30.0
# Nordic + BlueZ often rejects CCCD/notify if the ATT table is still settling.
GATT_SETTLE_SECONDS = 0.35
GATT_RETRY_ATTEMPTS = 3
_GATT_RETRY_MARKERS = (
    "unlikely_error",
    "unlikely error",
    "gatt protocol error",
    "error code.unlikely",
    ": 14>",
    "busy",
    "in progress",
    "connection refused",
    "le conn",
)


@dataclass(frozen=True, slots=True)
class BleTransportConfig:
    device_name: str = DEFAULT_DEVICE_NAME_NEEDLE
    scan_timeout_seconds: float = DEFAULT_SCAN_TIMEOUT_SECONDS
    start_command: bytes = DEFAULT_START_COMMAND
    auto_start_stream: bool = True
    settle_delay_seconds: float = GATT_SETTLE_SECONDS
    characteristic_uuid: str = NUS_TX_CHAR_UUID
    rx_characteristic_uuid: str = NUS_RX_CHAR_UUID


def is_retryable_gatt_error(exc: BaseException) -> bool:
    """True for transient ATT/BlueZ failures worth a short reconnect/retry."""
    blob = f"{type(exc).__name__} {exc!s} {exc!r}".lower()
    return any(marker in blob for marker in _GATT_RETRY_MARKERS)


def humanize_ble_error(exc: BaseException) -> str:
    """Polish operator copy. Never dump Bleak exception repr into the UI."""
    blob = f"{type(exc).__name__} {exc!s} {exc!r}".lower()
    if "timeout" in blob or "scan" in blob:
        return (
            "Nie znaleziono nakładki. Naciśnij raz przycisk na Triki, "
            "żeby się ogłosiła, i ponów połączenie."
        )
    if is_retryable_gatt_error(exc):
        return (
            "Nakładka odrzuciła połączenie Bluetooth. Zamknij inne programy "
            "(np. TrikiScope), naciśnij raz przycisk na Triki i ponów."
        )
    if "not found" in blob and "characteristic" in blob:
        return "Połączono, ale brakuje charakterystyki NUS. To nie wygląda na CAP001."
    if "bleak" in blob or "bluez" in blob or "dbus" in blob or "gatt" in blob:
        return (
            "Błąd Bluetooth. Naciśnij raz przycisk na nakładce i ponów. "
            "Jeśli wraca, zrestartuj adapter Bluetooth."
        )
    return "Nie udało się połączyć z Triki. Naciśnij przycisk na nakładce i ponów."


async def retry_gatt_op(op, *, attempts: int = GATT_RETRY_ATTEMPTS, delay_s: float = GATT_SETTLE_SECONDS):
    """Run an async GATT op, retrying transient Unlikely Error / busy."""
    last: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            return await op()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — classify then retry or raise
            last = exc
            if not is_retryable_gatt_error(exc) or attempt >= attempts - 1:
                raise
            if delay_s > 0:
                await asyncio.sleep(delay_s * (attempt + 1))
    assert last is not None
    raise last


def _require_bleak() -> tuple[object, object]:
    try:
        from bleak import BleakClient, BleakScanner
    except ImportError as exc:  # pragma: no cover - exercised when bleak absent
        raise ImportError(
            "BLE transport requires the optional 'ble' extra: "
            "pip install 'triki-controller[ble]' (bleak>=0.22.0)"
        ) from exc
    return BleakClient, BleakScanner


class BleTransport:
    """Async Bleak scan/connect/NUS-subscribe transport → ConnectionEvent + Notification.

    User prompt: print a clear **Scanning for Triki** state and instruct pressing
    the physical button once during the scan window.
    """

    def __init__(
        self,
        *,
        session_id: str,
        config: BleTransportConfig | None = None,
        prompt: Callable[[str], None] | None = None,
    ) -> None:
        self._session_id = session_id
        self._config = config or BleTransportConfig()
        self._prompt = prompt or (lambda msg: print(msg, flush=True))
        self._disconnected = False
        self._stop = asyncio.Event()
        self._event_seq = 0
        self._notification_seq = 0
        self._connection_epoch = 0
        self._client: object | None = None
        self._queue: asyncio.Queue[Notification | ConnectionEvent | None] = asyncio.Queue()

    async def disconnect(self) -> None:
        self._disconnected = True
        self._stop.set()
        await self._cleanup_client()

    def events(self) -> AsyncIterator[Notification | ConnectionEvent]:
        return self._events()

    async def _events(self) -> AsyncIterator[Notification | ConnectionEvent]:
        BleakClient, BleakScanner = _require_bleak()
        yield self._connection(
            ConnectionState.SCANNING,
            "Skanowanie — naciśnij raz przycisk na nakładce Triki.",
        )
        self._prompt(
            "Scanning for Triki — press the physical Triki button ONCE now "
            f"(wake advertising; scan window {self._config.scan_timeout_seconds:.0f}s)."
        )

        device = await self._scan(BleakScanner)
        if device is None or self._disconnected:
            yield self._connection(
                ConnectionState.DISCONNECTED,
                "Koniec skanowania — naciśnij raz przycisk na nakładce i połącz ponownie.",
            )
            return

        last_exc: BaseException | None = None
        for attempt in range(GATT_RETRY_ATTEMPTS):
            if self._disconnected:
                yield self._connection(ConnectionState.DISCONNECTED, "rozłączono przez użytkownika")
                return
            yield self._connection(
                ConnectionState.CONNECTING,
                "Łączenie z Triki…"
                if attempt == 0
                else f"Ponowna próba połączenia ({attempt + 1}/{GATT_RETRY_ATTEMPTS})…",
            )
            try:
                await self._connect_and_stream(BleakClient, device)
                last_exc = None
                break
            except asyncio.CancelledError:
                yield self._connection(ConnectionState.DISCONNECTED, "cancelled")
                raise
            except Exception as exc:  # noqa: BLE001 — retry transient GATT, else surface
                last_exc = exc
                await self._cleanup_client()
                if not is_retryable_gatt_error(exc) or attempt >= GATT_RETRY_ATTEMPTS - 1:
                    yield self._connection(ConnectionState.ERROR, humanize_ble_error(exc))
                    return
                await asyncio.sleep(GATT_SETTLE_SECONDS * (attempt + 1))

        if last_exc is not None:
            yield self._connection(ConnectionState.ERROR, humanize_ble_error(last_exc))
            return

        # Drain queue until disconnect sentinel.
        while True:
            item = await self._queue.get()
            if item is None:
                break
            yield item
            if isinstance(item, ConnectionEvent) and item.state in (
                ConnectionState.DISCONNECTED,
                ConnectionState.ERROR,
            ):
                # Keep draining until sentinel so producer can finish cleanly.
                continue

        await self._cleanup_client()

    async def _scan(self, BleakScanner: object) -> object | None:
        found: asyncio.Future[tuple[object, object]] = asyncio.get_running_loop().create_future()
        needle = self._config.device_name.lower()

        def detection(device: object, adv: object) -> None:
            local_name = getattr(adv, "local_name", None) or getattr(device, "name", None)
            if local_name and needle in str(local_name).lower() and not found.done():
                found.set_result((device, adv))

        scanner = BleakScanner(detection_callback=detection)  # type: ignore[operator]
        await scanner.start()
        try:
            device, _adv = await asyncio.wait_for(
                found, timeout=self._config.scan_timeout_seconds
            )
            return device
        except asyncio.TimeoutError:
            return None
        finally:
            await scanner.stop()

    async def _connect_and_stream(self, BleakClient: object, device: object) -> None:
        loop = asyncio.get_running_loop()
        if not self._disconnected:
            self._stop = asyncio.Event()

        def on_disconnect(_client: object) -> None:
            self._stop.set()

        client = BleakClient(device, disconnected_callback=on_disconnect)  # type: ignore[operator]
        self._client = client
        await client.connect()
        self._connection_epoch += 1
        await asyncio.sleep(GATT_SETTLE_SECONDS)

        tx = self._find_char(client, self._config.characteristic_uuid)
        if tx is None:
            await self._queue.put(
                self._connection(
                    ConnectionState.ERROR,
                    "Połączono, ale brakuje charakterystyki NUS TX.",
                )
            )
            await self._queue.put(None)
            return

        def handler(_sender: object, data: bytearray) -> None:
            received_ns = time.monotonic_ns()
            payload = bytes(data)

            def enqueue() -> None:
                self._notification_seq += 1
                self._queue.put_nowait(
                    Notification(
                        schema_version=SCHEMA_VERSION,
                        session_id=self._session_id,
                        connection_epoch=self._connection_epoch,
                        notification_seq=self._notification_seq,
                        received_monotonic_ns=received_ns,
                        characteristic_uuid=self._config.characteristic_uuid,
                        payload=payload,
                    )
                )

            loop.call_soon_threadsafe(enqueue)

        async def start_notify() -> None:
            await client.start_notify(tx, handler)

        await retry_gatt_op(start_notify)

        if self._config.auto_start_stream and self._config.start_command:
            delay = self._config.settle_delay_seconds
            if delay > 0:
                await asyncio.sleep(delay)
            rx = self._find_char(client, self._config.rx_characteristic_uuid)
            if rx is None:
                await self._queue.put(
                    self._connection(
                        ConnectionState.ERROR,
                        "Połączono, ale brakuje charakterystyki NUS RX — nie da się uruchomić strumienia.",
                    )
                )
                await self._queue.put(None)
                return

            async def write_start() -> None:
                await client.write_gatt_char(rx, self._config.start_command, response=False)

            await retry_gatt_op(write_start)

        await self._queue.put(
            self._connection(ConnectionState.STREAMING, "Połączono. Strumień IMU jest aktywny.")
        )

        async def waiter() -> None:
            await self._stop.wait()
            await self._queue.put(
                self._connection(
                    ConnectionState.DISCONNECTED,
                    "Rozłączono." if self._disconnected else "Nakładka się rozłączyła.",
                )
            )
            await self._queue.put(None)

        asyncio.create_task(waiter())

    def _find_char(self, client: object, uuid: str) -> object | None:
        target = uuid.lower()
        services = getattr(client, "services", None)
        if services is None:
            return None
        for service in services:
            for char in service.characteristics:
                if str(char.uuid).lower() == target:
                    return char
        return None

    async def _cleanup_client(self) -> None:
        client = self._client
        self._client = None
        if client is None:
            return
        try:
            if getattr(client, "is_connected", False):
                await client.disconnect()  # type: ignore[misc]
        except Exception:  # noqa: BLE001
            pass

    def _connection(self, state: ConnectionState, reason: str) -> ConnectionEvent:
        self._event_seq += 1
        return ConnectionEvent(
            schema_version=SCHEMA_VERSION,
            session_id=self._session_id,
            connection_epoch=self._connection_epoch,
            event_seq=self._event_seq,
            host_monotonic_ns=time.monotonic_ns(),
            state=state,
            reason=reason,
        )
