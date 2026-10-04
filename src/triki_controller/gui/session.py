"""Headless glue between the window and EmulatorRuntime.

The transport runs on an asyncio loop in a worker thread. The UI thread issues
commands and polls immutable snapshots; both sides share one lock. No BLE,
motion, or mapping logic lives here — only orchestration of existing modules.
"""

from __future__ import annotations

import asyncio
import importlib.util
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, replace
from enum import Enum
from typing import Callable

from triki_controller.core.models import (
    SCHEMA_VERSION,
    ConnectionEvent,
    ConnectionState,
    MappedState,
    MotionSample,
    Notification,
    OutputReceipt,
    ParseDiagnostic,
    RawSample,
)
from triki_controller.gui.settings import (
    PROFILE_NAMES,
    THRESHOLD_FIELDS,
    GuiSettings,
)
from triki_controller.motion.orientation import parse_orientation
from triki_controller.profiles.devices import (
    MEDIA_ORIENTATION,
    MOUSE_ORIENTATION,
    STEERING_ORIENTATION,
)
from triki_controller.output.trace import TraceOutput
from triki_controller.profiles.builtin import Profile, profile_by_name, with_overrides
from triki_controller.runtime.emulator import EmulatorRuntime

CALIBRATION_DURATION_S = 1.5
_CALIBRATION_GRACE_S = 3.0
_CALIBRATION_DETAIL_PL = {
    "need at least 5 samples": "za mało próbek (potrzeba co najmniej 5)",
    "accelerometer is not near 1 g": "akcelerometr nie wskazuje ~1 g — nakładka nie leży spokojnie",
    "gyro variance too high; previous bias kept": (
        "żyroskop zbyt niestabilny (ruch w trakcie pomiaru); zachowano poprzedni bias"
    ),
    "gyro bias updated": "zaktualizowano bias żyroskopu",
}
_ENDED = (ConnectionState.DISCONNECTED, ConnectionState.ERROR)


class OutputMode(str, Enum):
    OFF = "off"
    DRY_RUN = "dry-run"
    LIVE = "live"


@dataclass(frozen=True)
class CalibrationStatus:
    state: str = "idle"
    detail: str = "nie wykonano (bias 0)"
    bias_dps: tuple[float, float, float] | None = None
    samples: int = 0
    progress: float = 0.0


@dataclass(frozen=True)
class SessionSnapshot:
    transport: str | None
    connection: ConnectionState
    connection_reason: str | None
    samples: int
    sample_rate_hz: float | None
    parse_diagnostics: int
    battery_percent: float | None
    rssi_dbm: int | None
    raw: RawSample | None
    motion: MotionSample | None
    mapped: MappedState | None
    receipt: OutputReceipt | None
    pointer_px_per_s: tuple[float, float] | None
    recent_pulses: tuple[tuple[float, str], ...]
    output_mode: OutputMode
    output_note: str | None
    profile: Profile
    profile_name: str
    orientation: str
    thresholds: dict[str, float]
    pipeline: dict[str, str]
    calibration: CalibrationStatus
    error: str | None


def default_output_factory(live: bool) -> object:
    if live:
        from triki_controller.output.uinput_backend import UInputBackend

        return UInputBackend()
    return TraceOutput(history_limit=256)


async def _drain_tasks() -> None:
    tasks = [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=3.0)


def calibration_detail_pl(detail: str) -> str:
    return _CALIBRATION_DETAIL_PL.get(detail, detail)


class ControllerSession:
    def __init__(
        self,
        *,
        settings: GuiSettings | None = None,
        output_factory: Callable[[bool], object] = default_output_factory,
        ble_scan_timeout_s: float = 30.0,
    ) -> None:
        settings = settings or GuiSettings()
        self._lock = threading.RLock()
        self._output_factory = output_factory
        self._scan_timeout = ble_scan_timeout_s
        self._profile_name = settings.profile
        self._orientation = parse_orientation(settings.orientation)
        if settings.profile == "media":
            self._orientation = MEDIA_ORIENTATION
        elif settings.profile == "steering":
            self._orientation = STEERING_ORIENTATION
        elif settings.profile in {"mouse", "plane"}:
            self._orientation = MOUSE_ORIENTATION
        self._invert_pitch = settings.invert_pitch
        self._invert_roll = settings.invert_roll
        self._overrides = {name: dict(settings.thresholds.get(name, {})) for name in PROFILE_NAMES}
        self._axis_map = {name: dict(values) for name, values in settings.axis_map.items()}
        self._runtime = EmulatorRuntime(
            profile=self._build_profile(),
            output=output_factory(False),
            orientation=self._orientation,
        )
        self._runtime.mapper.set_axis_map(self._axis_map)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._task: object | None = None
        self._ble: object | None = None
        self._conn_id = 0
        self._event_seq = 0
        self._transport: str | None = None
        self._state = ConnectionState.DISCONNECTED
        self._reason: str | None = None
        self._output_mode = OutputMode.OFF
        self._output_note: str | None = None
        self._error: str | None = None
        self._calibration = CalibrationStatus()
        self._calib_window: list[RawSample] | None = None
        self._calib_deadline = 0.0
        self._bias: tuple[float, float, float] | None = None
        self._reset_stream()

    # -- commands (UI thread) -------------------------------------------------

    def connect(self, transport: str) -> str | None:
        if transport != "ble":
            return f"Nieznany transport {transport!r}"
        if importlib.util.find_spec("bleak") is None:
            return "Brak biblioteki bleak. Zainstaluj: pip install 'triki-controller[ble]'"
        with self._lock:
            if self._state not in _ENDED:
                return "Połączenie już trwa — najpierw rozłącz."
            self._conn_id += 1
            conn_id = self._conn_id
            self._transport = transport
            self._error = None
            self._output_note = None
            self._reset_stream()
            self._state = ConnectionState.SCANNING
            self._reason = None
        loop = self._ensure_loop()
        self._task = asyncio.run_coroutine_threadsafe(self._run_ble(conn_id), loop)
        return None

    def disconnect(self, reason: str = "rozłączono przez użytkownika") -> None:
        with self._lock:
            task, ble = self._task, self._ble
            self._task = None
            self._ble = None
            self._conn_id += 1
            self._stop_output_locked(reason)
            if self._state not in _ENDED:
                self._apply_connection(self._event(ConnectionState.DISCONNECTED, reason))
        loop = self._loop
        if loop is not None and ble is not None:
            asyncio.run_coroutine_threadsafe(ble.disconnect(), loop)  # type: ignore[attr-defined]
        if task is not None:
            task.cancel()  # type: ignore[attr-defined]

    def set_profile(self, name: str) -> str | None:
        if name not in PROFILE_NAMES:
            return f"Nieznany profil {name!r}"
        with self._lock:
            if name == self._profile_name:
                return None
            try:
                profile = self._build_profile(name)
            except ValueError as exc:
                return f"Nieprawidłowy profil: {exc}"
            self._profile_name = name
            self._pulses.clear()
            self._pointer.clear()
            # Locked mounts: media/mouse=horizontal, steering=vertical.
            if name == "media" and self._orientation != MEDIA_ORIENTATION:
                self._orientation = MEDIA_ORIENTATION
                self._runtime.set_orientation(MEDIA_ORIENTATION)
            elif name == "steering" and self._orientation != STEERING_ORIENTATION:
                self._orientation = STEERING_ORIENTATION
                self._runtime.set_orientation(STEERING_ORIENTATION)
            elif name in {"mouse", "plane"} and self._orientation != MOUSE_ORIENTATION:
                self._orientation = MOUSE_ORIENTATION
                self._runtime.set_orientation(MOUSE_ORIENTATION)
            return self._apply_profile_locked(profile)

    def set_inversion(self, *, invert_pitch: bool, invert_roll: bool) -> str | None:
        with self._lock:
            self._invert_pitch = invert_pitch
            self._invert_roll = invert_roll
            return self._apply_profile_locked(self._build_profile())

    def set_orientation(self, orientation: str) -> str | None:
        try:
            oid = parse_orientation(orientation)
        except ValueError as exc:
            return f"Nieprawidłowa orientacja: {exc}"
        with self._lock:
            if self._profile_name == "media":
                if self._orientation != MEDIA_ORIENTATION:
                    self._orientation = MEDIA_ORIENTATION
                    self._runtime.set_orientation(MEDIA_ORIENTATION)
                return "Muzyka zawsze używa orientacji poziomej — innych nie można wybrać."
            if self._profile_name == "steering":
                if self._orientation != STEERING_ORIENTATION:
                    self._orientation = STEERING_ORIENTATION
                    self._runtime.set_orientation(STEERING_ORIENTATION)
                return "Kierownica zawsze używa orientacji pionowej — innych nie można wybrać."
            if self._profile_name == "mouse":
                if self._orientation != MOUSE_ORIENTATION:
                    self._orientation = MOUSE_ORIENTATION
                    self._runtime.set_orientation(MOUSE_ORIENTATION)
                return "Mysz zawsze używa orientacji poziomej — innych nie można wybrać."
            if self._profile_name == "plane":
                if self._orientation != MOUSE_ORIENTATION:
                    self._orientation = MOUSE_ORIENTATION
                    self._runtime.set_orientation(MOUSE_ORIENTATION)
                return "Joystick zawsze używa orientacji poziomej — innych nie można wybrać."
            if oid == self._orientation:
                return None
            self._orientation = oid
            self._runtime.set_orientation(oid)
            return None

    def set_threshold(self, key: str, value: float) -> str | None:
        if key not in THRESHOLD_FIELDS:
            return f"Nieznany parametr {key!r}"
        with self._lock:
            candidate = dict(self._overrides[self._profile_name])
            candidate[key] = float(value)
            try:
                profile = self._build_profile(overrides=candidate)
            except ValueError as exc:
                return f"Nieprawidłowa wartość: {exc}"
            self._overrides[self._profile_name] = candidate
            return self._apply_profile_locked(profile)

    def set_thresholds(self, values: dict[str, float]) -> str | None:
        if set(values) - set(THRESHOLD_FIELDS):
            return "Nieznany parametr profilu"
        with self._lock:
            candidate = dict(self._overrides[self._profile_name])
            candidate.update(values)
            try:
                profile = self._build_profile(overrides=candidate)
            except (ValueError, TypeError) as exc:
                return f"Nieprawidłowe ustawienia: {exc}"
            self._overrides[self._profile_name] = candidate
            return self._apply_profile_locked(profile)

    def reset_thresholds(self) -> str | None:
        with self._lock:
            self._overrides[self._profile_name] = {}
            return self._apply_profile_locked(self._build_profile())

    def thresholds(self) -> dict[str, float]:
        with self._lock:
            profile = self._runtime.profile
            return {key: float(getattr(profile, key)) for key in THRESHOLD_FIELDS}

    def start_output(self, *, live: bool) -> str | None:
        with self._lock:
            return self._start_output_locked(live=live)

    def stop_output(self, reason: str = "zatrzymano przez użytkownika") -> None:
        with self._lock:
            self._stop_output_locked(reason)

    def recenter(self) -> str | None:
        with self._lock:
            if self._state != ConnectionState.STREAMING or self._motion is None:
                return "Najpierw połącz się z Triki."
            self._runtime.recenter()
            return None

    def begin_calibration(self, duration_s: float = CALIBRATION_DURATION_S) -> str | None:
        with self._lock:
            if self._state != ConnectionState.STREAMING:
                return "Najpierw połącz się z Triki."
            if self._calib_window is not None:
                return "Kalibracja już trwa."
            self._calib_window = []
            self._calib_duration_ns = int(duration_s * 1_000_000_000)
            self._calib_deadline = time.monotonic() + duration_s + _CALIBRATION_GRACE_S
            self._calibration = CalibrationStatus(
                "collecting", "pomiar — nie ruszaj nakładką", self._bias, 0
            )
            return None

    def current_settings(self) -> GuiSettings:
        with self._lock:
            return GuiSettings(
                profile=self._profile_name,
                orientation=self._orientation,
                invert_pitch=self._invert_pitch,
                invert_roll=self._invert_roll,
                thresholds={name: dict(v) for name, v in self._overrides.items() if v},
                axis_map={name: dict(values) for name, values in self._axis_map.items()},
            )

    def apply_settings(self, settings: GuiSettings) -> str | None:
        with self._lock:
            overrides = {name: dict(settings.thresholds.get(name, {})) for name in PROFILE_NAMES}
            try:
                orientation = parse_orientation(settings.orientation)
                profile = with_overrides(
                    profile_by_name(
                        settings.profile,
                        invert_pitch=settings.invert_pitch,
                        invert_roll=settings.invert_roll,
                    ),
                    **overrides[settings.profile],
                )
            except ValueError as exc:
                return f"Nieprawidłowe ustawienia: {exc}"
            self._overrides = overrides
            self._axis_map = {name: dict(values) for name, values in settings.axis_map.items()}
            self._runtime.mapper.set_axis_map(self._axis_map)
            self._invert_pitch = settings.invert_pitch
            self._invert_roll = settings.invert_roll
            self._profile_name = settings.profile
            if settings.profile == "media":
                orientation = MEDIA_ORIENTATION
            elif settings.profile == "steering":
                orientation = STEERING_ORIENTATION
            elif settings.profile == "mouse":
                orientation = MOUSE_ORIENTATION
            self._orientation = orientation
            self._runtime.set_orientation(orientation)
            return self._apply_profile_locked(profile)

    def snapshot(self) -> SessionSnapshot:
        with self._lock:
            if self._calib_window is not None and time.monotonic() > self._calib_deadline:
                self._finish_calibration_rejected("za mało próbek w oknie kalibracji")
            pointer = self._pointer_rate()
            return SessionSnapshot(
                transport=self._transport,
                connection=self._state,
                connection_reason=self._reason,
                samples=self._samples,
                sample_rate_hz=self._rate(),
                parse_diagnostics=self._parse_diagnostics,
                battery_percent=None if self._raw is None else self._raw.battery_percent,
                rssi_dbm=None if self._raw is None else self._raw.rssi_dbm,
                raw=self._raw,
                motion=self._motion,
                mapped=self._mapped,
                receipt=self._receipt,
                pointer_px_per_s=pointer,
                recent_pulses=tuple(self._pulses),
                output_mode=self._output_mode,
                output_note=self._output_note,
                profile=self._runtime.profile,
                profile_name=self._profile_name,
                orientation=self._orientation,
                thresholds={k: float(getattr(self._runtime.profile, k)) for k in THRESHOLD_FIELDS},
                pipeline=self._runtime.pipeline_status().as_dict(),
                calibration=self._calibration,
                error=self._error,
            )

    def shutdown(self) -> None:
        self.disconnect("zamknięcie programu")
        loop = self._loop
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(_drain_tasks(), loop).result(4.0)
        except Exception:  # noqa: BLE001 — closing anyway; inputs are already neutral
            pass
        loop.call_soon_threadsafe(loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
        if not loop.is_running():
            loop.close()
        self._loop = None
        self._thread = None

    # -- worker side ----------------------------------------------------------

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="triki-transport", daemon=True)
            thread.start()
            self._loop = loop
            self._thread = thread
        return self._loop

    async def _run_ble(self, conn_id: int) -> None:
        from triki_controller.protocol.cap001_hypothesis import Cap001HypothesisFrameParser
        from triki_controller.transport.ble import BleTransport, BleTransportConfig

        transport = BleTransport(
            session_id=f"gui-ble-{uuid.uuid4()}",
            config=BleTransportConfig(scan_timeout_seconds=self._scan_timeout),
            prompt=lambda _message: None,
        )
        with self._lock:
            if conn_id != self._conn_id:
                return
            self._ble = transport
        parser = Cap001HypothesisFrameParser()
        ended = False
        try:
            async for event in transport.events():
                if conn_id != self._conn_id:
                    break
                if isinstance(event, ConnectionEvent):
                    if event.state == ConnectionState.STREAMING:
                        parser.reset(event.connection_epoch)
                    self._on_connection(conn_id, event)
                    if event.state in _ENDED:
                        ended = True
                        break
                    continue
                if not isinstance(event, Notification):
                    continue
                for item in parser.feed(event):
                    if isinstance(item, ParseDiagnostic):
                        with self._lock:
                            self._parse_diagnostics += 1
                    elif isinstance(item, RawSample):
                        self._on_sample(conn_id, item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — surface as connection state
            ended = True
            from triki_controller.transport.ble import humanize_ble_error

            self._on_connection(conn_id, self._event(ConnectionState.ERROR, humanize_ble_error(exc)))
        finally:
            try:
                await transport.disconnect()
            except Exception:  # noqa: BLE001
                pass
            if not ended:
                self._on_connection(
                    conn_id, self._event(ConnectionState.DISCONNECTED, "transport BLE zakończony")
                )

    def _on_connection(self, conn_id: int, event: ConnectionEvent) -> None:
        with self._lock:
            if conn_id != self._conn_id:
                return
            self._apply_connection(event)

    def _on_sample(self, conn_id: int, sample: RawSample) -> bool:
        with self._lock:
            if conn_id != self._conn_id:
                return False
            try:
                step = self._runtime.feed(sample)
            except Exception as exc:  # noqa: BLE001 — never leave inputs held on a crash
                self._error = f"Błąd potoku: {exc!r}"
                self._stop_output_locked("błąd potoku")
                return True
            self._samples += 1
            self._times.append(sample.received_monotonic_ns)
            self._raw = sample
            self._motion = step.motion
            self._mapped = step.mapped
            self._receipt = step.receipt
            now = time.monotonic()
            for pulse in step.mapped.pulses:
                self._pulses.append((now, pulse))
            self._note_mpris_errors(step.receipt)
            dt = step.motion.dt_s
            if dt and dt > 0 and step.mapped.relative_deltas:
                self._pointer.append(
                    (
                        dt,
                        step.mapped.relative_deltas.get("pointer_x", 0.0),
                        step.mapped.relative_deltas.get("pointer_y", 0.0),
                    )
                )
            if self._calib_window is not None:
                self._collect_calibration(sample)
            return True

    # -- helpers (lock held) --------------------------------------------------

    def _apply_connection(self, event: ConnectionEvent) -> None:
        was_active = self._runtime.active
        self._state = event.state
        self._reason = event.reason
        if event.state == ConnectionState.STREAMING:
            self._reset_stream()
        self._runtime.handle_connection(event)
        if event.state in _ENDED:
            if was_active:
                self._output_note = f"Wyjście zatrzymane i zneutralizowane: {event.reason}"
            self._output_mode = OutputMode.OFF
            if self._calib_window is not None:
                self._finish_calibration_rejected("przerwano — utracono połączenie")

    def _note_mpris_errors(self, receipt: OutputReceipt | None) -> None:
        """Surface player-volume failures in the GUI without raising."""
        if receipt is None or not receipt.detail:
            return
        detail = receipt.detail
        if "mpris:" not in detail:
            return
        # Prefer the first mpris soft-error fragment for the status line.
        parts = [part.strip() for part in detail.split(";") if "mpris:" in part]
        if not parts:
            return
        note = parts[0]
        if note.startswith("mpris dry-run"):
            return
        # Fallback notes are informational; keep them visible while Live.
        self._output_note = note

    def _media_live_status_note(self) -> str:
        """Clear Live status: which MPRIS player, volume capability, uinput fallback."""
        mpris = getattr(self._runtime.output, "_mpris", None) or getattr(
            self._runtime.output, "mpris", None
        )
        if mpris is None:
            return (
                "Wyjście Live aktywne — brak adaptera MPRIS. "
                "Transport przez uinput; głośność odtwarzacza niedostępna."
            )
        if hasattr(mpris, "describe_status"):
            status = mpris.describe_status()
            detail = getattr(status, "detail", None) or ""
            volume = getattr(status, "volume", None)
            writable = getattr(status, "volume_writable", None)
            if writable is False or (status.active_player is None and status.playerctl_available):
                return f"Wyjście Live aktywne. {detail}"
            if volume is not None and writable is not False and status.active_player:
                return (
                    f"Wyjście Live aktywne — {detail} "
                    f"Kręć w prawo/lewo (0–100%, bez odkręcania)."
                )
            return f"Wyjście Live aktywne. {detail}"
        reading = mpris.read_volume() if hasattr(mpris, "read_volume") else None
        if reading is None and getattr(mpris, "last_error", None):
            return str(mpris.last_error)
        if reading is None:
            return (
                "Wyjście Live aktywne, ale nie znaleziono odtwarzacza MPRIS. "
                "Play/pause/next/prev mogą iść przez uinput; głośność wymaga MPRIS "
                "(Pear Desktop: Plugins → Shortcuts (& MPRIS))."
            )
        return (
            f"Wyjście Live aktywne — głośność odtwarzacza {reading:.0%}. "
            f"Kręć w prawo/lewo (0–100%, bez odkręcania)."
        )

    def _start_output_locked(self, *, live: bool) -> str | None:
        if self._state != ConnectionState.STREAMING:
            return "Najpierw połącz się z Triki."
        if self._runtime.active:
            self._runtime.deactivate("zmiana trybu wyjścia", keep_origin=True)
        try:
            self._runtime.set_output(self._output_factory(live))
            self._runtime.activate(live=live)
        except Exception as exc:  # noqa: BLE001 — uinput permission, missing evdev
            self._runtime.deactivate("błąd uruchomienia wyjścia", keep_origin=True)
            self._runtime.set_output(TraceOutput(history_limit=256))
            self._output_mode = OutputMode.OFF
            self._output_note = f"Nie udało się uruchomić wyjścia: {exc}"
            return self._output_note
        self._output_mode = OutputMode.LIVE if live else OutputMode.DRY_RUN
        if self._profile_name == "media" and live:
            self._output_note = self._media_live_status_note()
        elif live:
            self._output_note = "Wyjście Live aktywne — zdarzenia idą do systemu."
        else:
            self._output_note = (
                "Wyjście próbne (dry-run) — bez sterowania systemem. "
                "Wybierz „Na żywo” i Start, albo połącz ponownie z Live."
            )
        return None

    def _stop_output_locked(self, reason: str) -> None:
        if self._runtime.active:
            self._runtime.deactivate(reason, keep_origin=True)
            self._output_note = f"Wyjście zatrzymane: {reason}"
        self._output_mode = OutputMode.OFF

    def _apply_profile_locked(self, profile: Profile) -> str | None:
        try:
            self._runtime.set_profile(profile)
        except Exception as exc:  # noqa: BLE001 — reopening uinput can fail
            self._runtime.deactivate("błąd zmiany profilu", keep_origin=True)
            self._output_mode = OutputMode.OFF
            self._output_note = f"Wyjście zatrzymane po błędzie zmiany profilu: {exc}"
            return self._output_note
        return None

    def _build_profile(
        self, name: str | None = None, overrides: dict[str, float] | None = None
    ) -> Profile:
        name = name or self._profile_name
        base = profile_by_name(
            name, invert_pitch=self._invert_pitch, invert_roll=self._invert_roll
        )
        values = self._overrides[name] if overrides is None else overrides
        return with_overrides(base, **values)

    def _collect_calibration(self, sample: RawSample) -> None:
        window = self._calib_window
        assert window is not None
        window.append(sample)
        span = window[-1].received_monotonic_ns - window[0].received_monotonic_ns
        self._calibration = replace(
            self._calibration,
            samples=len(window),
            progress=min(1.0, span / self._calib_duration_ns),
        )
        if span < self._calib_duration_ns or len(window) < 5:
            return
        result = self._runtime.calibrate(window)
        self._calib_window = None
        if result.accepted:
            self._bias = result.gyro_bias_dps
            self._calibration = CalibrationStatus(
                "accepted", calibration_detail_pl(result.detail), self._bias, len(window), 1.0
            )
        else:
            self._calibration = CalibrationStatus(
                "rejected", calibration_detail_pl(result.detail), self._bias, len(window), 1.0
            )

    def _finish_calibration_rejected(self, detail: str) -> None:
        count = 0 if self._calib_window is None else len(self._calib_window)
        self._calib_window = None
        self._calibration = CalibrationStatus(
            "rejected", f"{detail}; zachowano poprzedni bias", self._bias, count
        )

    def _reset_stream(self) -> None:
        self._samples = 0
        self._parse_diagnostics = 0
        self._times: deque[int] = deque(maxlen=50)
        self._pointer: deque[tuple[float, float, float]] = deque(maxlen=10)
        self._pulses: deque[tuple[float, str]] = deque(maxlen=8)
        self._raw: RawSample | None = None
        self._motion: MotionSample | None = None
        self._mapped: MappedState | None = None
        self._receipt: OutputReceipt | None = None

    def _rate(self) -> float | None:
        if len(self._times) < 2:
            return None
        span = self._times[-1] - self._times[0]
        if span <= 0:
            return None
        return (len(self._times) - 1) / (span / 1_000_000_000)

    def _pointer_rate(self) -> tuple[float, float] | None:
        if not self._pointer:
            return None
        total = sum(item[0] for item in self._pointer)
        if total <= 0:
            return None
        return (
            sum(item[1] for item in self._pointer) / total,
            sum(item[2] for item in self._pointer) / total,
        )

    def _event(self, state: ConnectionState, reason: str) -> ConnectionEvent:
        with self._lock:
            self._event_seq += 1
            return ConnectionEvent(
                schema_version=SCHEMA_VERSION,
                session_id="gui",
                connection_epoch=self._conn_id,
                event_seq=self._event_seq,
                host_monotonic_ns=time.monotonic_ns(),
                state=state,
                reason=reason,
            )
