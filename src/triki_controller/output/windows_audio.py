"""Per-process Core Audio sessions and the separate default multimedia endpoint.

No Linux imports, subprocesses, or master-volume fallback for app failures.
Only immutable scalar snapshots cross the dedicated COM worker boundary.
Native pointers are reacquired and released on that worker per operation.
Supported pycaw APIs: AudioDevice.AudioSessionManager/EndpointVolume,
AudioSession.SimpleAudioVolume and AudioUtilities.GetAllDevices/GetSpeakers.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PlayerSession:
    key: str
    name: str
    active: bool
    volume: float
    muted: bool


@dataclass(frozen=True)
class Endpoint:
    key: str
    volume: float


@dataclass(frozen=True)
class WindowsAudioStatus:
    players: tuple[str, ...]
    active_player: str | None
    volume: float | None
    volume_writable: bool | None
    detail: str


def _level(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('non-finite volume')
    return max(0.0, min(1.0, value))


class WindowsAudio:
    """Rebase each player generation onto the incoming mapped knob level.

    Pin survives rescan until the process disappears. Core Audio Active means
    a running audio stream, not a claim that media position is advancing.
    Audio sessions are grouped by process (PID plus start time), not exe name.
    Each generation's first frame is read-only: actual volume and incoming
    mapped level become the baseline/origin. Later frames follow their delta.
    Mute/unmute, explicit cycles, and failures invalidate that translation.
    read_volume/describe_status are observational; runtime baseline capture
    must call reset_player first (WindowsOutputBackend's compatibility seam).
    """
    def __init__(self, *, adapter=None, clock=time.monotonic,
                 scan_interval=.45, write_interval=.04, epsilon=.008):
        self.adapter: Any = adapter if adapter is not None else PycawAudioAdapter()
        self._clock = clock
        self._scan_interval = max(0.0, scan_interval)
        self._write_interval = max(0.0, write_interval)
        self._epsilon = max(0.0, epsilon)
        self._lock = threading.RLock()
        self._sessions: tuple[PlayerSession, ...] = ()
        self._scan_at = float('-inf')
        self._pinned = None
        self._manual_player = None
        self._selected = None
        self._last_player = None
        self._player_baseline = self._player_origin = None
        self._baseline_update = None
        self._player_muted = None
        self._player_at = float('-inf')
        self._endpoint = None
        self._baseline = self._origin = self._last_system = None
        self._system_at = float('-inf')
        self.last_error = None

    @property
    def active(self):
        return self._baseline is not None

    def list_media_players(self) -> list[tuple[str, str]]:
        with self._lock:
            # sessions() marshals all native enumeration through its COM worker.
            return [(p.key, p.name) for p in sorted(self.adapter.sessions(), key=lambda p: p.key)]

    def select_media_player(self, player_id: str | None) -> None:
        with self._lock:
            self._manual_player = player_id
            self._pinned = player_id
            self._selected = None
            self.reset_player()

    def _select(self, force=False):
        now = self._clock()
        if force or now - self._scan_at >= self._scan_interval:
            self._sessions = tuple(sorted(self.adapter.sessions(), key=lambda p: p.key))
            self._scan_at = now
        by_key = {p.key: p for p in self._sessions}
        if self._manual_player is not None:
            selected = by_key.get(self._manual_player)
            if selected is None:
                self._selected = None
                raise RuntimeError(f'selected player unavailable: {self._manual_player}; no substitution')
            if selected.key != self._selected:
                self._selected = selected.key
                self.reset_player(invalidate_scan=False)
            return selected
        if self._pinned not in by_key:
            self._pinned = None
        selected = by_key.get(self._pinned) if self._pinned is not None else None
        if selected is None and self._sessions:
            selected = min(self._sessions, key=lambda p: (not p.active, p.name.casefold(), p.key))
        key = selected.key if selected else None
        if key != self._selected:
            self._selected = key
            self.reset_player(invalidate_scan=False)
        if selected is None:
            raise RuntimeError('no running application audio sessions; no system fallback')
        return selected

    def reset_player(self, *, invalidate_scan=True):
        """Forget mapping offset, never write/restore the user's actual level."""
        with self._lock:
            self._player_baseline = self._player_origin = None
            self._baseline_update = None
            self._player_muted = None
            self._last_player = None
            self._player_at = float('-inf')
            if invalidate_scan:
                self._scan_at = float('-inf')

    def take_media_baseline(self):
        """Align translation with the mapper only after its safe target rebase."""
        with self._lock:
            baseline = self._baseline_update
            self._baseline_update = None
            if baseline is not None:
                self._player_origin = baseline
            return baseline

    def _failed(self, scope, exc):
        self.last_error = f'{scope}: {exc}'
        if scope == 'player':
            self.reset_player()
        else:
            self.leave()
        return self.last_error

    def read_volume(self):
        with self._lock:
            try:
                level = self._select(force=True).volume
                self.last_error = None
                return level
            except Exception as exc:
                self._failed('player', exc)
                return None

    def check_transport_target(self):
        """Validate a manual pin read-only; Auto keeps legacy global transport.

        Native identity discovery does not require readable volume. Older inert
        adapters can use their scalar session snapshots; discovery errors fail
        closed and are reported as errors, not as proof the player is missing.
        """
        with self._lock:
            if self._manual_player is None:
                return None
            try:
                available = getattr(self.adapter, 'player_available', None)
                found = (available(self._manual_player) if available is not None
                         else any(p.key == self._manual_player for p in self.adapter.sessions()))
                if not found:
                    return f'selected player unavailable: {self._manual_player}; no substitution'
                return None
            except Exception as exc:
                return f'selected player discovery failed: {self._manual_player}: {exc}'

    def describe_status(self):
        with self._lock:
            volume = self.read_volume()
            return WindowsAudioStatus(
                players=tuple(p.name for p in self._sessions), active_player=self._selected,
                volume=volume, volume_writable=True if volume is not None else None,
                detail=self.last_error or f'Windows Core Audio app volume: {self._selected}; transport: global media keys',
            )

    def apply_level(self, level):
        with self._lock:
            try:
                incoming = float(level)
                if not math.isfinite(incoming):
                    raise ValueError('non-finite volume')
                # Baseline reads/status may have populated an older snapshot.
                # Reacquire actual volume for the first frame of a translation.
                player = self._select(force=self._player_baseline is None
                                      and self._player_muted is not True)
                if player.muted != self._player_muted:
                    self.reset_player(invalidate_scan=False)
                    self._player_muted = player.muted
                if player.muted:
                    self.last_error = None
                    return None
                if self._player_baseline is None:
                    # Capture both domains: old mapper absolute levels must not
                    # overwrite a cycled, restarted, or newly available app.
                    self._player_baseline = _level(player.volume)
                    self._player_origin = incoming
                    self._last_player = self._player_baseline
                    self._baseline_update = self._player_baseline
                    self._player_at = self._clock()
                    self.last_error = None
                    return None
                assert self._player_origin is not None
                target = _level(self._player_baseline + incoming - self._player_origin)
                if self._last_player is not None and abs(target - self._last_player) < self._epsilon:
                    if target not in (0.0, 1.0) or target == self._last_player:
                        return None
                now = self._clock()
                if now - self._player_at < self._write_interval:
                    return None
                self.adapter.set_player(player.key, target)
                self._last_player = target
                self._player_at = now
                self.last_error = None
                return None
            except Exception as exc:
                return self._failed('player', exc)

    def apply_pulse(self, pulse):
        with self._lock:
            try:
                player = self._select(force=True)
                if pulse == 'cycle_player':
                    keys = [p.key for p in self._sessions]
                    self._pinned = keys[(keys.index(player.key) + 1) % len(keys)]
                    self._selected = self._pinned
                    self.reset_player()
                elif pulse == 'mute':
                    self.adapter.set_mute(player.key, not player.muted)
                    self.reset_player()
                elif pulse in {'volume_up', 'volume_down'}:
                    target = _level(player.volume + (.05 if pulse == 'volume_up' else -.05))
                    self.adapter.set_player(player.key, target)
                    self.reset_player()
                else:
                    raise ValueError(f'unsupported player pulse {pulse!r}')
                self.last_error = None
                return None
            except Exception as exc:
                return self._failed('player', exc)

    def apply_offset(self, offset):
        with self._lock:
            try:
                offset = float(offset)
                if not math.isfinite(offset):
                    raise ValueError('non-finite system offset')
                now = self._clock()
                if now - self._system_at < self._write_interval:
                    return None
                endpoint = self.adapter.default_endpoint()
                if self._baseline is None or endpoint.key != self._endpoint:
                    # First inverted frame/switch is read-only: no sudden jump.
                    self._endpoint = endpoint.key
                    self._baseline = _level(endpoint.volume)
                    self._origin = offset
                    self._last_system = self._baseline
                    self._system_at = now
                    self.last_error = None
                    return None
                target = _level(self._baseline + offset - self._origin)
                if self._last_system is None or abs(target - self._last_system) >= self._epsilon:
                    self.adapter.set_endpoint(endpoint.key, target)
                    self._last_system = target
                self._system_at = now
                self.last_error = None
                return None
            except Exception as exc:
                return self._failed('system', exc)

    def leave(self):
        with self._lock:
            self._endpoint = None
            self._baseline = self._origin = self._last_system = None
            self._system_at = float('-inf')

    def close(self):
        with self._lock:
            self.leave()
            self.adapter.close()


class PycawAudioAdapter:
    """Serialize COM on a dedicated thread; return only Python scalar records.

    UI activation/baseline reads and BLE apply/neutralize run on different
    caller threads. A lock alone cannot make COM interfaces transferable.
    No raw pointers or exception tracebacks leave the native worker.
    runtime_factory is an injectable native boundary for ownership tests.
    """
    def __init__(self, *, runtime_factory=None):
        if runtime_factory is None and sys.platform != 'win32':
            raise RuntimeError('Windows Core Audio is available only on Windows')
        self._factory = runtime_factory or _CoreAudioRuntime
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='triki-core-audio')
        self._lock = threading.RLock()
        self._closed = False

    def _call(self, operation, *args) -> Any:
        with self._lock:
            if self._closed:
                raise RuntimeError('Core Audio adapter is closed')
            ok, result = self._pool.submit(self._invoke, operation, args).result()
            if not ok:
                raise RuntimeError(result)
            return result

    def _invoke(self, operation, args):
        try:
            with self._factory() as runtime:
                # Catch inside the apartment so traceback-owned COM references
                # die before CoUninitialize; do not return exception objects.
                return _capture(runtime, operation, args)
        except Exception as exc:
            return False, str(exc)

    def sessions(self):
        return self._call('sessions')

    def player_available(self, key):
        return self._call('player_available', key)

    def set_player(self, key, level):
        self._call('set_player', key, _level(level))

    def set_mute(self, key, muted):
        self._call('set_mute', key, bool(muted))

    def default_endpoint(self):
        return self._call('default_endpoint')

    def set_endpoint(self, key, level):
        self._call('set_endpoint', key, _level(level))

    def close(self):
        with self._lock:
            self._closed = True
            self._pool.shutdown(wait=True)


def _capture(runtime, operation, args):
    try:
        return True, getattr(runtime, operation)(*args)
    except Exception as exc:
        return False, str(exc)


class _CoreAudioRuntime:
    """One native call's COM apartment, never shared with caller threads."""
    def __enter__(self):
        # comtypes automatically initializes its first importing thread. Balance
        # that implicit initialization before explicitly entering our MTA.
        first_import = 'comtypes' not in sys.modules
        try:
            import comtypes
        except ImportError as exc:
            raise RuntimeError('Windows audio requires pycaw, comtypes and psutil') from exc
        if first_import:
            comtypes.CoUninitialize()
        comtypes.CoInitializeEx(0)
        self.com = comtypes
        try:
            from pycaw.pycaw import AudioUtilities, AudioSession
            from pycaw.api.audiopolicy import IAudioSessionControl2
            self.utilities = AudioUtilities
            self.session_class = AudioSession
            self.control_class = IAudioSessionControl2
        except Exception:
            comtypes.CoUninitialize()
            raise
        return self

    def __exit__(self, *exc):
        self.com.CoUninitialize()

    def _sessions(self):
        # GetAllSessions() enumerates only the default endpoint. Enumerate all
        # active render endpoints so routed/headphone app audio still works.
        for device in self.utilities.GetAllDevices(data_flow=0, device_state=1):
            enumerator = device.AudioSessionManager.GetSessionEnumerator()
            for index in range(enumerator.GetCount()):
                control = enumerator.GetSession(index)
                if control is None:
                    continue
                session = self.session_class(control.QueryInterface(self.control_class))
                if session.ProcessId == 0 or session.State == 2:
                    continue  # System Sounds and expired sessions are not players.
                process = session.Process
                if process is None:
                    continue
                # Process discovery can race exit; skip only process lookup
                # failures, not audio COM failures which must surface.
                try:
                    key = f'{session.ProcessId}:{process.create_time()}'
                    name = process.name()
                except Exception:
                    continue
                yield key, name, session

    def sessions(self):
        groups = {}
        for key, name, session in self._sessions():
            volume = session.SimpleAudioVolume
            current = PlayerSession(key, name, session.State == 1,
                                    float(volume.GetMasterVolume()), bool(volume.GetMute()))
            previous = groups.get(key)
            # Prefer an active session's baseline; unify all process sessions on
            # write, and treat the process muted only when all sessions are mute.
            if previous is None:
                groups[key] = current
            else:
                preferred = current if current.active and not previous.active else previous
                groups[key] = PlayerSession(key, name, previous.active or current.active,
                                            preferred.volume, previous.muted and current.muted)
        return tuple(groups.values())

    def player_available(self, key):
        # Identity-only enumeration: unreadable/muted volume is not absence.
        return any(candidate == key for candidate, _, _ in self._sessions())

    def _change_player(self, key, method, value):
        found = False
        for candidate, _, session in self._sessions():
            if candidate == key:
                found = True
                volume = session.SimpleAudioVolume
                getattr(volume, method)(value, None)
                actual = volume.GetMasterVolume() if method == 'SetMasterVolume' else volume.GetMute()
                if abs(float(actual) - float(value)) > .02:
                    raise RuntimeError('application audio session did not accept volume/mute')
        if not found:
            raise RuntimeError('selected application disconnected; no system fallback')

    def set_player(self, key, level):
        self._change_player(key, 'SetMasterVolume', level)

    def set_mute(self, key, muted):
        self._change_player(key, 'SetMute', int(muted))

    def default_endpoint(self):
        device = self.utilities.GetSpeakers()
        if device is None:
            raise RuntimeError('no default multimedia render endpoint')
        return Endpoint(device.id, float(device.EndpointVolume.GetMasterVolumeLevelScalar()))

    def set_endpoint(self, key, level):
        device = self.utilities.GetSpeakers()
        if device is None or device.id != key:
            raise RuntimeError('default endpoint changed/disconnected; rebase on next frame')
        volume = device.EndpointVolume
        volume.SetMasterVolumeLevelScalar(level, None)
        if abs(float(volume.GetMasterVolumeLevelScalar()) - level) > .02:
            raise RuntimeError('default endpoint did not accept volume')
