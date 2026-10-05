"""macOS audio adapters. No Linux mixer or global volume-key fallback.

System volume uses identity-addressed CoreAudio through ctypes. Player events
are addressed to a *running PID*, never a bundle URL which could launch it.
Music/Spotify terminology is checked against the installed app's sdef.
Native paths need macOS validation; importing this file is platform-neutral.
"""
from __future__ import annotations

from triki_controller.gui.media_favorite import selector_favorite, unique_favorite_target

import ctypes
from dataclasses import dataclass
import math
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Protocol


class MacOSAudioError(RuntimeError):
    """Unavailable audio, denied Automation, or unsupported app/device."""


class AudioAdapter(Protocol):
    def read_system_endpoint(self) -> tuple[object, float]: ...
    def write_system_endpoint(self, endpoint: object, level: float) -> None: ...
    def player_identity(self, player: str) -> object: ...
    def list_players(self) -> tuple[str, ...]: ...
    def read_player(self, player: str) -> float: ...
    def write_player_target(self, player: str, identity: object, level: float) -> None: ...
    def transport(self, player: str, pulse: str) -> None: ...


def _finite(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise MacOSAudioError("volume must be finite")
    return value


def _level(value: float) -> float:
    return max(0.0, min(1.0, _finite(value)))


def _valid_level(value: float) -> float:
    value = _finite(value)
    if not 0 <= value <= 1:
        raise MacOSAudioError("invalid native volume response")
    return value


@dataclass(frozen=True)
class MacOSEndpoint:
    device_id: int
    uid: str


class AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [("mSelector", ctypes.c_uint32), ("mScope", ctypes.c_uint32),
                ("mElement", ctypes.c_uint32)]


class CoreAudioSystem:
    """Injectable stdlib HAL boundary; only a readable main output scalar.

    Apple AudioObjectGet/SetPropertyData uses UInt32 sizes, Float32 scalar,
    OSStatus (SInt32), Boolean (UInt8) and CFIndex (signed long). CFString
    device UID ownership is returned to the caller, released after conversion.
    No default-target AppleScript fallback: channel-only/fixed-volume devices
    are unsupported rather than guessing a scalar or overwriting balance.
    Reference: developer.apple.com/documentation/coreaudio and corefoundation.
    """
    GLOBAL = int.from_bytes(b"glob", "big")
    OUTPUT = int.from_bytes(b"outp", "big")
    DEFAULT = int.from_bytes(b"dOut", "big")
    UID = int.from_bytes(b"uid ", "big")
    VOLUME = int.from_bytes(b"volm", "big")
    UTF8 = 0x08000100

    def __init__(self, *, coreaudio=None, corefoundation=None):
        if coreaudio is None or corefoundation is None:
            if sys.platform != "darwin":
                raise MacOSAudioError("native CoreAudio requires macOS")
            try:
                coreaudio = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
                corefoundation = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
            except OSError as exc:
                raise MacOSAudioError(f"CoreAudio unavailable: {exc}") from exc
        self.ca, self.cf = coreaudio, corefoundation
        address = ctypes.POINTER(AudioObjectPropertyAddress)
        u32, ptr = ctypes.c_uint32, ctypes.c_void_p
        self._bind(self.ca.AudioObjectGetPropertyData, ctypes.c_int32,
                   [u32, address, u32, ptr, ctypes.POINTER(u32), ptr])
        self._bind(self.ca.AudioObjectSetPropertyData, ctypes.c_int32,
                   [u32, address, u32, ptr, u32, ptr])
        self._bind(self.ca.AudioObjectHasProperty, ctypes.c_ubyte, [u32, address])
        self._bind(self.ca.AudioObjectIsPropertySettable, ctypes.c_int32,
                   [u32, address, ctypes.POINTER(ctypes.c_ubyte)])
        self._bind(self.cf.CFStringGetLength, ctypes.c_long, [ptr])
        self._bind(self.cf.CFStringGetMaximumSizeForEncoding, ctypes.c_long, [ctypes.c_long, u32])
        self._bind(self.cf.CFStringGetCString, ctypes.c_ubyte,
                   [ptr, ctypes.POINTER(ctypes.c_char), ctypes.c_long, u32])
        self._bind(self.cf.CFRelease, None, [ptr])

    @staticmethod
    def _bind(fn, result, args):
        fn.restype, fn.argtypes = result, args

    @staticmethod
    def _check(status):
        if status:
            raise MacOSAudioError(f"CoreAudio OSStatus {status}")

    def _get(self, device, selector, scope, value):
        address = AudioObjectPropertyAddress(selector, scope, 0)
        size = ctypes.c_uint32(ctypes.sizeof(value))
        self._check(self.ca.AudioObjectGetPropertyData(device, ctypes.byref(address),
                    0, None, ctypes.byref(size), ctypes.byref(value)))
        if size.value != ctypes.sizeof(value):
            raise MacOSAudioError("CoreAudio invalid property data size")
        return value

    def _default(self):
        device = self._get(1, self.DEFAULT, self.GLOBAL, ctypes.c_uint32()).value
        if not device:
            raise MacOSAudioError("default output identity unavailable")
        return device

    def _identity(self, device):
        ref = self._get(device, self.UID, self.GLOBAL, ctypes.c_void_p())
        if not ref.value:
            raise MacOSAudioError("default output identity unavailable (null UID)")
        try:
            length = self.cf.CFStringGetLength(ref)
            size = self.cf.CFStringGetMaximumSizeForEncoding(length, self.UTF8) + 1
            if not 1 <= size <= 1048576:
                raise MacOSAudioError("invalid default output identity size")
            buffer = ctypes.create_string_buffer(size)
            if not self.cf.CFStringGetCString(ref, buffer, size, self.UTF8):
                raise MacOSAudioError("default output identity UTF-8 conversion failed")
            try:
                uid = buffer.value.decode("utf-8")
            except UnicodeError as exc:
                raise MacOSAudioError("invalid default output identity UTF-8") from exc
            if not uid:
                raise MacOSAudioError("default output identity unavailable (empty UID)")
            return MacOSEndpoint(device, uid)
        finally:
            self.cf.CFRelease(ref)

    def _scalar(self, device):
        address = AudioObjectPropertyAddress(self.VOLUME, self.OUTPUT, 0)
        if not self.ca.AudioObjectHasProperty(device, ctypes.byref(address)):
            raise MacOSAudioError("output device has no supported main volume scalar")
        return _valid_level(self._get(device, self.VOLUME, self.OUTPUT, ctypes.c_float()).value)

    def read_endpoint(self):
        device = self._default()
        endpoint = self._identity(device)
        level = self._scalar(device)
        if self._default() != device or self._identity(device) != endpoint:
            raise MacOSAudioError("default output changed during read; rebase required")
        return endpoint, level

    def write_endpoint(self, endpoint, level):
        target = _level(level)
        if not isinstance(endpoint, MacOSEndpoint) or endpoint.device_id <= 0 or not endpoint.uid:
            raise MacOSAudioError("captured output identity unavailable; refusing write")
        current, _ = self.read_endpoint()
        if current != endpoint:
            raise MacOSAudioError("default output changed before write; rebase required")
        address = AudioObjectPropertyAddress(self.VOLUME, self.OUTPUT, 0)
        writable = ctypes.c_ubyte()
        self._check(self.ca.AudioObjectIsPropertySettable(endpoint.device_id,
                    ctypes.byref(address), ctypes.byref(writable)))
        if not writable.value:
            raise MacOSAudioError("output scalar is not writable (fixed-volume device)")
        # Recheck UID after capability query, then write the captured AudioObjectID,
        # NOT the current default. A switch after this check cannot retarget the call.
        if self._default() != endpoint.device_id or self._identity(endpoint.device_id) != endpoint:
            raise MacOSAudioError("default output changed before write; rebase required")
        value = ctypes.c_float(target)
        self._check(self.ca.AudioObjectSetPropertyData(endpoint.device_id, ctypes.byref(address),
                    0, None, ctypes.sizeof(value), ctypes.byref(value)))
        current, actual = self.read_endpoint()
        if current != endpoint:
            raise MacOSAudioError("default output changed during write; rebase required")
        # HAL can apply asynchronously. No unverified success: a delayed readback
        # returns an error and the next frame recaptures instead of retrying a stale baseline.
        if abs(actual - target) > 0.015:
            raise MacOSAudioError("system volume not applied/readback unconfirmed")


class NativeMacOSAudio:
    """Lazy Cocoa/ScriptingBridge; targets only existing Music/Spotify PIDs.

    Requires pyobjc-framework-Cocoa and pyobjc-framework-ScriptingBridge for
    players, and Automation permission. CoreAudio needs neither PyObjC nor
    Accessibility. Read-only player queries can still request Automation.
    """
    BUNDLES = {"Music": "com.apple.Music", "Spotify": "com.spotify.client"}
    COMMANDS = {"play_pause": "playpause", "next_track": "nextTrack",
                "previous_track": "previousTrack"}
    TERMS = {"play_pause": "playpause", "next_track": "next track",
             "previous_track": "previous track"}

    def __init__(self, *, run=None, system=None):
        self._run = run or subprocess.run
        self._dictionaries = {}
        self._system = system

    def _system_adapter(self):
        if self._system is None:
            self._system = CoreAudioSystem()
        return self._system

    def read_system_endpoint(self):
        return self._system_adapter().read_endpoint()

    def write_system_endpoint(self, endpoint, level):
        self._system_adapter().write_endpoint(endpoint, level)

    def read_system(self) -> float:
        return self.read_system_endpoint()[1]

    def write_system(self, level: float) -> None:
        endpoint, _ = self.read_system_endpoint()
        self.write_system_endpoint(endpoint, level)

    @staticmethod
    def _frameworks():
        if sys.platform != "darwin":
            raise MacOSAudioError("native player control requires macOS")
        try:
            from AppKit import NSRunningApplication
            from ScriptingBridge import SBApplication
        except ImportError as exc:
            raise MacOSAudioError("player control needs pyobjc-framework-Cocoa and "
                                  "pyobjc-framework-ScriptingBridge") from exc
        return NSRunningApplication, SBApplication

    def list_players(self) -> tuple[str, ...]:
        running, _ = self._frameworks()
        return tuple(name for name, bundle in self.BUNDLES.items()
                     if any(not app.isTerminated() for app in
                            running.runningApplicationsWithBundleIdentifier_(bundle)))

    def _process(self, player):
        if player not in self.BUNDLES:
            raise MacOSAudioError("unsupported player/browser audio; only running Music/Spotify "
                                  "are supported; no system-volume fallback")
        running, _ = self._frameworks()
        processes = [app for app in running.runningApplicationsWithBundleIdentifier_(
            self.BUNDLES[player]) if not app.isTerminated()]
        if not processes:
            raise MacOSAudioError(f"{player} is not running; will not launch it")
        if len(processes) != 1:
            raise MacOSAudioError(f"{player} process identity ambiguous; refusing target")
        return processes[0]

    @staticmethod
    def _process_identity(process):
        # launchDate distinguishes PID reuse as well as ordinary restarts.
        launched = process.launchDate()
        if launched is None:
            raise MacOSAudioError("player process identity unavailable (launch date)")
        pid = int(process.processIdentifier())
        started = float(launched.timeIntervalSince1970())
        if pid <= 0 or not math.isfinite(started):
            raise MacOSAudioError("invalid player process identity")
        return pid, started

    def player_identity(self, player):
        return self.BUNDLES.get(player), self._process_identity(self._process(player))

    def _target(self, player: str, term: str, identity=None):
        process = self._process(player)
        _, scripting = self._frameworks()
        if identity is not None and (self.BUNDLES[player], self._process_identity(process)) != identity:
            raise MacOSAudioError("player identity changed before write; rebase required")
        path = str(process.bundleURL().path())
        if path not in self._dictionaries:
            try:
                result = self._run(["/usr/bin/sdef", path], capture_output=True,
                                   text=True, timeout=2, check=False)
                if result.returncode:
                    raise MacOSAudioError(f"cannot inspect {player} dictionary: {result.stderr}")
                # ElementTree does not fetch the standard external sdef DTD;
                # reject entity declarations/internal subsets to prevent expansion.
                declarations = result.stdout.upper()
                if "<!ENTITY" in declarations or ("<!DOCTYPE" in declarations and
                        "[" in declarations.split("<!DOCTYPE", 1)[1].split(">", 1)[0]):
                    raise MacOSAudioError(f"unsafe {player} scripting dictionary")
                root = ET.fromstring(result.stdout)
            except (OSError, subprocess.TimeoutExpired, ET.ParseError) as exc:
                raise MacOSAudioError(f"cannot inspect {player} dictionary: {exc}") from exc
            self._dictionaries[path] = {(element.tag, element.get("name")):
                                       element.attrib for element in root.iter()}
        kind = "property" if term == "sound volume" else "command"
        entry = self._dictionaries[path].get((kind, term))
        if entry is None or (kind == "property" and entry.get("access") == "r"):
            raise MacOSAudioError(f"{player} dictionary does not support writable {term}")
        # PID addressing cannot automatically relaunch a terminated application.
        if process.isTerminated():
            raise MacOSAudioError(f"{player} stopped; no launch attempted")
        if identity is not None and self.player_identity(player) != identity:
            raise MacOSAudioError("player identity changed before event; rebase required")
        app = scripting.applicationWithProcessIdentifier_(process.processIdentifier())
        if app is None or not app.isRunning():
            raise MacOSAudioError(f"{player} stopped; no launch attempted")
        app.setTimeout_(120)  # AppleEvent timeout is ticks (60 per second).
        return app

    @staticmethod
    def _check(app):
        error = app.lastError()
        if error is not None:
            raise MacOSAudioError(f"player AppleEvent failed: {error}; check macOS "
                                  "Privacy & Security > Automation (denial may be -1743)")

    def read_player(self, player: str) -> float:
        app = self._target(player, "sound volume")
        value = app.soundVolume()
        self._check(app)
        if value is None:
            raise MacOSAudioError(f"{player} returned no volume")
        try:
            value = float(value) / 100
        except (TypeError, ValueError) as exc:
            raise MacOSAudioError(f"{player} returned invalid volume") from exc
        if not math.isfinite(value) or not 0 <= value <= 1:
            raise MacOSAudioError(f"{player} returned invalid volume")
        return value

    def write_player(self, player: str, level: float) -> None:
        self.write_player_target(player, self.player_identity(player), level)

    def write_player_target(self, player, identity, level):
        if not identity:
            raise MacOSAudioError("player identity unavailable; refusing write")
        target = int(round(_level(level) * 100))
        app = self._target(player, "sound volume", identity)
        if self.player_identity(player) != identity:
            raise MacOSAudioError("player identity changed before setter; rebase required")
        app.setSoundVolume_(target)
        self._check(app)
        actual = self.read_player(player)
        if self.player_identity(player) != identity:
            raise MacOSAudioError("player identity changed during write; rebase required")
        if abs(actual - target / 100) > 0.015:
            raise MacOSAudioError(f"{player} did not apply volume")

    def transport(self, player: str, pulse: str) -> None:
        if pulse not in self.TERMS:
            raise MacOSAudioError(f"unsupported transport {pulse!r}")
        app = self._target(player, self.TERMS[pulse])
        getattr(app, self.COMMANDS[pulse])()
        self._check(app)


class MacOSSystemVolume:
    """Mapped system_volume is an OFFSET, present only while inverted.

    Capture actual output volume and the mapped origin on entry. First frame
    never writes. Leaving/neutralizing forgets the baseline, never restores it.
    """
    def __init__(self, *, adapter: AudioAdapter | None = None):
        self.adapter = adapter or NativeMacOSAudio()
        self._baseline = self._origin = self._last = self._endpoint = None
        self.last_error = None

    @property
    def active(self):
        return self._baseline is not None

    def leave(self):
        self._baseline = self._origin = self._last = self._endpoint = None

    def read_level(self):
        try:
            endpoint, level = self.adapter.read_system_endpoint()
            if not endpoint:
                raise MacOSAudioError("default output identity unavailable")
            level = _valid_level(level)
            self.last_error = None
            return level
        except Exception as exc:  # Native Objective-C bridge errors must become receipt detail.
            self.leave()
            self.last_error = f"system: {exc}"
            return None

    def apply_offset(self, offset):
        try:
            offset = _finite(offset)
            endpoint, level = self.adapter.read_system_endpoint()
            if not endpoint:
                raise MacOSAudioError("default output identity unavailable; refusing write")
            level = _valid_level(level)
            if not self.active or endpoint != self._endpoint:
                self._endpoint = endpoint
                self._baseline = self._last = level
                self._origin = offset
            else:
                assert self._baseline is not None and self._origin is not None
                assert self._last is not None
                target = _level(self._baseline + offset - self._origin)
                if abs(target - self._last) >= 0.008:
                    self.adapter.write_system_endpoint(self._endpoint, target)
                    self._last = target
            self.last_error = None
            return None
        except Exception as exc:  # Native Objective-C bridge errors must become receipt detail.
            self.leave()
            self.last_error = f"system: {exc}"
            return self.last_error


@dataclass(frozen=True)
class MacOSPlayerStatus:
    active_player: str | None
    volume: float | None
    volume_writable: bool
    detail: str


class MacOSPlayerVolume:
    """Rebase mapped player_volume at target changes, then preserve knob deltas.

    Selection is pinned by cycle_player. Mute restoration is per process identity;
    neutralization forgets input translation and never resets user volume.
    """
    def __init__(self, *, adapter: AudioAdapter | None = None):
        self.adapter = adapter or NativeMacOSAudio()
        self._selected = None
        self._identity = None
        self._last = self._input = self._position = None
        self._baseline_update = None
        self._saved = {}
        self._manual_player = None
        self.last_error = None

    def leave(self):
        self._last = self._input = self._position = None
        self._baseline_update = None

    def take_media_baseline(self):
        """Optional runtime handshake: reseed existing mapper, without modifying it.

        Delta translation also works without this hook; consuming it prevents a
        clamped mapper from saturating at the *old* player's 0/1 boundaries.
        """
        baseline = self._baseline_update
        self._baseline_update = None
        if baseline is not None:
            self._input = baseline
        return baseline

    def list_media_players(self) -> list[tuple[str, str]]:
        return [(name, name) for name in self.adapter.list_players()]

    def _favorite_candidates(self, players):
        candidates = []
        for player in players:
            identity = self.adapter.player_identity(player)
            app_id = identity[0] if isinstance(identity, tuple) and identity else None
            if not isinstance(app_id, str) or not app_id:
                raise ValueError("Stable macOS bundle identity unavailable")
            candidates.append((player, app_id))
        return candidates

    def favorite_media_descriptors(self, player_ids=None) -> dict[str, dict[str, str]]:
        """Read each bundle identity once, without changing selected/baseline state."""
        players = self.adapter.list_players() if player_ids is None else player_ids
        entries = {}
        for player in dict.fromkeys(players):
            try:
                identity = self.adapter.player_identity(player)
                app_id = identity[0] if isinstance(identity, tuple) and identity else None
                if isinstance(app_id, str) and app_id:
                    entries[player] = app_id
            except (ValueError, MacOSAudioError):
                pass
        counts = {}
        for app in entries.values():
            counts[app] = counts.get(app, 0) + 1
        return {p: {"platform": "macos", "app_id": app, "label": p}
                for p, app in entries.items() if counts[app] == 1}

    def favorite_media_descriptor(self, player_id: str) -> dict[str, str]:
        players = self.adapter.list_players()
        if player_id not in players:
            raise ValueError("Selected player unavailable")
        candidates = self._favorite_candidates(players)
        app_id = next(app for key, app in candidates if key == player_id)
        descriptor = {"platform": "macos", "app_id": app_id, "label": player_id}
        unique_favorite_target(descriptor, candidates)
        return descriptor

    def select_media_player(self, player_id: str | None) -> None:
        self._manual_player = player_id
        self._selected = player_id
        self._identity = None
        self.leave()

    def _select(self):
        players = self.adapter.list_players()
        favorite = selector_favorite(self._manual_player, "macos")
        target = (unique_favorite_target(favorite, self._favorite_candidates(players))
                  if favorite is not None else self._manual_player)
        if target is not None and target not in players:
            self.leave()
            raise MacOSAudioError(f"selected player unavailable: {self._manual_player}; no substitution")
        if target is not None:
            self._selected = target
        if not players:
            self._selected = None
            self.leave()
            raise MacOSAudioError("no supported running Music/Spotify player; arbitrary "
                                  "browser audio unsupported; no system-volume fallback")
        if self._selected not in players:
            self._selected = players[0]
            self.leave()
        identity = self.adapter.player_identity(self._selected)
        if not identity:
            raise MacOSAudioError("player identity unavailable; refusing write")
        if identity != self._identity:
            self._identity = identity
            self.leave()
        return self._selected

    def _read(self, player):
        current = _valid_level(self.adapter.read_player(player))
        if self.adapter.player_identity(player) != self._identity:
            raise MacOSAudioError("player identity changed during read; rebase required")
        return current

    def describe_status(self):
        """Observational availability query: never re-arm a readable target."""
        try:
            player = self._select()
            current = self._read(player)
            # read_player checks installed sdef writable sound-volume terminology.
            self.last_error = None
            return MacOSPlayerStatus(player, current, True,
                                     f"{player}: sound volume {current:.0%}; no system fallback")
        except Exception as exc:
            self.leave()
            self.last_error = f"player: {exc}"
            return MacOSPlayerStatus(None, None, False, self.last_error)

    def read_volume(self):
        # Explicit connect/recenter resets the mapper: drop any old translation.
        self.leave()
        try:
            current = self._read(self._select())
            self._position = self._last = current
            self.last_error = None
            return current
        except Exception as exc:  # Native Objective-C bridge errors must become receipt detail.
            self.leave()
            self.last_error = f"player: {exc}"
            return None

    def _guard(self, action):
        try:
            action()
            self.last_error = None
            return None
        except Exception as exc:  # Native Objective-C bridge errors must become receipt detail.
            self.leave()
            self.last_error = f"player: {exc}"
            return self.last_error

    def apply_level(self, level):
        def action():
            incoming = _finite(level)
            player = self._select()
            if self._input is None:
                if self._position is None:
                    self._position = self._last = self._read(player)
                self._input = incoming
                self._baseline_update = self._position
                return  # First frame for this identity is always read-only.
            delta = incoming - self._input
            self._input = incoming
            if self._identity in self._saved:
                return  # Consume motion while muted; never replay it on unmute.
            assert self._position is not None and self._last is not None
            target = _level(self._position + delta)
            self._position = target
            if (abs(target - self._last) >= 0.008
                    or (target in (0.0, 1.0) and target != self._last)):
                self.adapter.write_player_target(player, self._identity, target)
                self._last = target
        return self._guard(action)

    def apply_pulse(self, pulse):
        def action():
            player = self._select()
            if pulse == "cycle_player":
                players = self.adapter.list_players()
                self._selected = players[(players.index(player) + 1) % len(players)]
                self.leave()
                return
            if pulse == "mute":
                if self._identity in self._saved:
                    self.adapter.write_player_target(player, self._identity, self._saved[self._identity])
                    del self._saved[self._identity]
                else:
                    current = self._read(player)
                    self.adapter.write_player_target(player, self._identity, 0.0)
                    self._saved[self._identity] = current
            elif pulse in {"volume_up", "volume_down"}:
                current = self._read(player)
                target = _level(current + (0.05 if pulse == "volume_up" else -0.05))
                self.adapter.write_player_target(player, self._identity, target)
                if target > 0:
                    self._saved.pop(self._identity, None)
            else:
                raise MacOSAudioError(f"unsupported pulse {pulse!r}")
            self.leave()
        return self._guard(action)

    def handles_transport(self, pulse):
        return pulse in NativeMacOSAudio.COMMANDS

    def apply_transport(self, pulse):
        return self._guard(lambda: self.adapter.transport(self._select(), pulse))
