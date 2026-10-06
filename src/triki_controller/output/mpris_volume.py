"""Active-player control via MPRIS (playerctl), not system mixer keys.

KEY_VOLUMEUP / KEY_VOLUMEDOWN from uinput typically hit the desktop mixer
(system-wide). Media profile volume goes here instead so only the current
player changes. The pot never uses KEY_VOLUMEUP. When MPRIS Volume is a stub
(Pear Desktop / Chromium MediaSession), volume falls back to that player's
PipeWire/Pulse sink-input — still per-app, never the default sink.

Player selection prefers actually playing (status Playing and MPRIS position
advancing), then stale Playing, then Paused, then Stopped. Within a tier:
writable-known > non-chromium > list order. Volume writability is tracked
per player so a Chromium MediaSession stub failure does not block others.
Every playerctl command pins `-p <player>`.
"""

from __future__ import annotations

import json
import shutil
from triki_controller.gui.media_favorite import selector_favorite, unique_favorite_target
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from triki_controller.output.app_stream_volume import AppStreamVolume

VOLUME_STEP = 0.05
_DEFAULT_RESTORE = 0.5
# Steady IMU samples must not re-list MPRIS every frame. That scan runs on the
# BLE thread and delays play/pause. Auto-select still runs on this interval.
_VOLUME_RESCAN_S = 0.45
_VOLUME_PULSES = frozenset({"volume_up", "volume_down", "mute", "cycle_player"})
_TRANSPORT_PULSES = {
    "play_pause": "play-pause",
    "next_track": "next",
    "previous_track": "previous",
}
_VOLUME_EPSILON = 0.008
_VOLUME_VERIFY_TOLERANCE = 0.05
_STALE_POSITION_S = 0.05
_STATUS_RANK = {"Playing": 0, "Paused": 1, "Stopped": 2}

RunFn = Callable[[list[str], float], subprocess.CompletedProcess[str]]


def _default_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@dataclass(frozen=True)
class MprisPlayerStatus:
    """Snapshot used by GUI / activate notes. Never invents a player."""

    playerctl_available: bool
    players: tuple[str, ...]
    active_player: str | None
    identity: str | None
    volume: float | None
    volume_writable: bool | None
    detail: str


class MprisPlayerVolume:
    """Adjust org.mpris.MediaPlayer2.Player for the selected MPRIS player."""

    def __init__(
        self,
        *,
        run: RunFn | None = None,
        dry_run: bool = False,
        step: float = VOLUME_STEP,
        playerctl_path: str | None = None,
        stream: AppStreamVolume | None = None,
    ) -> None:
        self._run = run or _default_run
        self._dry_run = dry_run
        self._step = max(0.01, min(0.25, float(step)))
        self._playerctl = playerctl_path
        self._stream = stream or AppStreamVolume(run=self._run)
        self._saved_volume: float | None = None
        self._muted = False
        self._last_set: float | None = None
        self._last_applied_player: str | None = None
        self._last_position: dict[str, float] = {}
        self._writable_players: set[str] = set()
        self._unwritable_players: set[str] = set()
        self._stream_players: set[str] = set()
        self._cached_identity: str | None = None
        self._cached_player: str | None = None
        self._pinned_player: str | None = None
        self._manual_player: str | None = None
        self._volume_scan_mono = 0.0
        self.last_error: str | None = None
        self.log: list[str] = []
        self._manual_baseline = self._manual_origin = self._baseline_update = None
        self._manual_rebase = False
        self._translation_player = None
        self._favorite_generation = None

    def list_media_players(self) -> list[tuple[str, str]]:
        binary = self._resolve_playerctl()
        if binary is None:
            return []
        # Listing is observational: do not use _read_identity (it changes caches).
        return [(name, self._friendly_name(name, None)) for name in self._list_players(binary)]

    def _desktop_entry(self, player: str) -> str | None:
        busctl = shutil.which("busctl")
        if busctl is None:
            return None
        try:
            result = self._run([busctl, "--user", "get-property",
                                player if player.startswith(":") else f"org.mpris.MediaPlayer2.{player}",
                                "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2", "DesktopEntry"], 1.5)
            text = (result.stdout or "").strip()
            value = json.loads(text[2:]) if result.returncode == 0 and text.startswith("s ") else None
            return value if isinstance(value, str) and value.strip() else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None

    def _bus_owner(self, player: str) -> str | None:
        busctl = shutil.which("busctl")
        if busctl is None:
            return None
        try:
            result = self._run([busctl, "--user", "call", "org.freedesktop.DBus",
                                "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                "GetNameOwner", "s", f"org.mpris.MediaPlayer2.{player}"], 1.5)
            text = (result.stdout or "").strip()
            value = json.loads(text[2:]) if result.returncode == 0 and text.startswith("s ") else None
            return value if isinstance(value, str) and value.startswith(":") else None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            return None

    def favorite_media_descriptors(self, player_ids=None) -> dict[str, dict[str, str]]:
        """Detached observational snapshot; never reuse it to authorize a star/write.

        The picker supplies its already listed names. Capture every owner before
        reading metadata from unique destinations, then recheck all aliases.
        """
        if player_ids is None:
            binary = self._resolve_playerctl()
            player_ids = self._list_players(binary) if binary else ()
        players = tuple(dict.fromkeys(player_ids))
        owners = {p: self._bus_owner(p) for p in players}
        entries = {p: self._desktop_entry(owner) if owner else None
                   for p, owner in owners.items()}
        stable = {p: bool(owner and self._bus_owner(p) == owner)
                  for p, owner in owners.items()}
        counts = {}
        for app in entries.values():
            if app:
                counts[app] = counts.get(app, 0) + 1
        return {p: {"platform": "mpris", "app_id": app, "label": p}
                for p, app in entries.items()
                if app and stable[p] and counts[app] == 1}

    def favorite_media_descriptor(self, player_id: str) -> dict[str, str]:
        binary = self._resolve_playerctl()
        players = self._list_players(binary) if binary else ()
        if player_id not in players:
            raise ValueError("Selected player unavailable")
        owners = {p: self._bus_owner(p) for p in players}
        entries = [(p, self._desktop_entry(owner) if owner else None)
                   for p, owner in owners.items()]
        app_id = next(app for p, app in entries if p == player_id)
        if owners[player_id] is None or self._bus_owner(player_id) != owners[player_id]:
            raise ValueError("Selected player owner changed; cannot favorite stale metadata")
        if not app_id:
            raise ValueError("Stable MPRIS DesktopEntry unavailable; cannot favorite guessed labels or instance suffixes")
        descriptor = {"platform": "mpris", "app_id": app_id, "label": player_id}
        unique_favorite_target(descriptor, entries)
        return descriptor

    def select_media_player(self, player_id: str | None) -> None:
        self._invalidate_favorite_generation()
        self._manual_player = player_id
        self._manual_rebase = True
        self._manual_baseline = self._manual_origin = self._baseline_update = None
        self._pinned_player = player_id
        self._cached_player = self._cached_identity = None
        self._last_set = self._last_applied_player = None
        self._saved_volume = None
        self._muted = False
        self._volume_scan_mono = 0.0

    def _invalidate_favorite_generation(self):
        """Forget instance-owned state without changing the stored selection."""
        if self._favorite_generation is not None:
            player = self._favorite_generation[0]
            self._writable_players.discard(player)
            self._unwritable_players.discard(player)
            self._stream_players.discard(player)
            self._last_position.pop(player, None)
        self._favorite_generation = None
        self._saved_volume = None
        self._muted = False
        self._cached_identity = None
        self._translation_player = None
        self._manual_rebase = True
        self.reset_player()

    def reset_player(self):
        # Legacy automatic mode remains direct; explicit picker translations
        # must be rearmed when runtime recenter/connect captures a fresh level.
        if self._manual_baseline is not None or self._manual_rebase:
            self._manual_rebase = True
            self._manual_baseline = self._manual_origin = self._baseline_update = None
            self._last_set = self._last_applied_player = None

    def take_media_baseline(self):
        # Linux receipts can report soft volume failures as applied input frames.
        # Keep the update pending until player-volume delivery succeeds.
        if self.last_error:
            return None
        baseline = self._baseline_update
        self._baseline_update = None
        if baseline is not None:
            self._manual_origin = baseline
        return baseline

    def handles(self, pulse: str) -> bool:
        return pulse in _VOLUME_PULSES

    def handles_transport(self, pulse: str) -> bool:
        return pulse in _TRANSPORT_PULSES

    def read_volume(self) -> float | None:
        """Explicit runtime baseline read; status/listing stay observational."""
        self.reset_player()
        if self._dry_run:
            return self._last_set if self._last_set is not None else 0.5
        binary = self._resolve_playerctl()
        if binary is None:
            return None
        player = self._select_player(binary)
        if player is None:
            return None
        if self._should_use_stream(player):
            # Spotify desktop Volume can be a stub; baseline the actual app stream.
            stream_vol = self._stream.read_level(self._stream_target(player))
            if stream_vol is not None or self._is_spotify(player):
                return stream_vol
        return self._read_volume(binary, player)

    def describe_status(self) -> MprisPlayerStatus:
        """Human-facing capability summary for the media Live path."""
        if self._dry_run:
            return MprisPlayerStatus(
                playerctl_available=True,
                players=("dry-run",),
                active_player="dry-run",
                identity=None,
                volume=self._last_set if self._last_set is not None else 0.5,
                volume_writable=True,
                detail="dry-run MPRIS (bez sterowania systemem)",
            )
        binary = self._resolve_playerctl()
        if binary is None:
            detail = "mpris: brak playerctl — zainstaluj playerctl, żeby sterować odtwarzaczem"
            self.last_error = detail
            return MprisPlayerStatus(
                playerctl_available=False,
                players=(),
                active_player=None,
                identity=None,
                volume=None,
                volume_writable=None,
                detail=detail,
            )
        players = self._list_players(binary)
        if not players:
            detail = (
                "mpris: brak odtwarzacza MPRIS. Play/pause/next/prev idą przez "
                "globalne klawisze uinput (jeśli aplikacja je obsługuje). "
                "Głośność wymaga MPRIS — dla Pear Desktop włącz Plugins → "
                "Shortcuts (& MPRIS) i zrestartuj aplikację."
            )
            self.last_error = detail
            return MprisPlayerStatus(
                playerctl_available=True,
                players=(),
                active_player=None,
                identity=None,
                volume=None,
                volume_writable=None,
                detail=detail,
            )
        active = self._select_player(binary, players)
        if active is None:
            return MprisPlayerStatus(True, players, None, None, None, None,
                                     self.last_error or "selected player unavailable")
        identity = self._read_identity(binary, active)
        volume = self._read_volume(binary, active)
        stream_volume = None
        stub = self._looks_like_chromium_stub(active, identity)
        if self._should_use_stream(active):
            stream_volume = self._stream.read_level(self._stream_target(active))
            volume = stream_volume
        self._cached_player = active
        self._cached_identity = identity
        label = self._friendly_name(active, identity)
        writable = self._volume_writable_for(active)
        if stream_volume is not None:
            writable = True
        elif stub or self._is_spotify(active):
            writable = None
        if stream_volume is not None:
            detail = (
                f"mpris: aktywny {label} — głośność aplikacji {volume:.0%} "
                f"(strumień audio aplikacji przez PipeWire/Pulse). "
                f"Transport: MPRIS, przy braku komendy → uinput."
            )
        elif self._is_spotify(active):
            detail = (
                "Spotify: brak lokalnego strumienia audio. Uruchom odtwarzanie na tym komputerze; "
                "sterowanie głośnością używa PipeWire/Pulse, nie miksera systemowego. "
                "Sprawdź, czy Spotify Connect nie odtwarza na innym urządzeniu."
            )
        elif writable is False:
            detail = self._volume_unwritable_message(label)
        elif self._pinned_player == active:
            if volume is None:
                detail = (
                    f"mpris: przypięty {label} — potrząśnij całym urządzeniem Triki, "
                    "żeby zmienić odtwarzacz."
                )
            else:
                detail = (
                    f"mpris: przypięty {label} (potrząśnij całym urządzeniem Triki, "
                    f"żeby zmienić). Głośność {volume:.0%}."
                )
        elif stub:
            detail = (
                f"mpris: aktywny {label} (Chromium MediaSession). "
                f"Głośność przez strumień audio aplikacji, gdy Pear faktycznie gra. "
                f"Suwak w Pear może dalej pokazywać brak MPRIS Volume. "
                f"Opcjonalnie: Plugins → Shortcuts (& MPRIS). Transport → uinput."
            )
        elif volume is None:
            detail = (
                f"mpris: aktywny {label}, ale Volume niedostępne. "
                f"Transport: MPRIS z fallbackiem uinput."
            )
        else:
            writable_text = "zapisywalna" if writable is not False else "tylko odczyt"
            detail = (
                f"mpris: aktywny {label} — głośność {volume:.0%} ({writable_text}). "
                f"Transport: MPRIS, przy braku komendy → uinput."
            )
        return MprisPlayerStatus(
            playerctl_available=True,
            players=players,
            active_player=active,
            identity=identity,
            volume=volume,
            volume_writable=writable,
            detail=detail,
        )

    def apply_level(self, level: float) -> str | None:
        """Set absolute player volume. Reselects on an interval; skips tiny writes."""
        target = max(0.0, min(1.0, float(level)))
        if self._dry_run:
            if self._last_set is not None and abs(target - self._last_set) < _VOLUME_EPSILON:
                return None
            self._last_set = target
            self.log.append(f"mpris dry-run volume={target:.3f}")
            self.last_error = None
            return None
        binary = self._resolve_playerctl()
        if binary is None:
            self.last_error = "mpris: brak playerctl — głośność odtwarzacza niedostępna"
            return self.last_error
        player = self._player_for_volume(binary)
        if player is None:
            self.last_error = self.last_error or "mpris: brak odtwarzacza MPRIS — głośność niedostępna"
            return self.last_error
        if self._manual_baseline is not None and player != self._translation_player:
            self.reset_player()
        if self._manual_rebase:
            actual = self.read_volume()
            if actual is None:
                return self.last_error or "selected player volume unavailable"
            self._translation_player = self._cached_player
            self._manual_baseline = actual
            self._manual_origin = target
            self._baseline_update = actual
            # A read-only rebase already knows the target's current level;
            # do not issue a redundant write on the first synchronized frame.
            self._last_set = actual
            self._last_applied_player = player
            self._manual_rebase = False
            self.last_error = None
            return None
        if self._manual_baseline is not None:
            target = max(0.0, min(1.0, self._manual_baseline + target - self._manual_origin))
        if (
            player == self._last_applied_player
            and self._last_set is not None
            and abs(target - self._last_set) < _VOLUME_EPSILON
            and (target not in (0.0, 1.0) or target == self._last_set)
        ):
            self.last_error = None
            return None
        if self._muted:
            return None
        if self._should_use_stream(player):
            return self._apply_stream_level(player, target)
        try:
            err = self._exec(binary, player, ["volume", f"{target:.3f}"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = f"mpris: {exc}"
            return self.last_error
        if err:
            self.last_error = err
            return err
        verify_err = self._verify_volume(binary, player, target)
        if verify_err:
            stream_err = self._apply_stream_level(player, target)
            if stream_err is None:
                return None
            return verify_err
        self._last_set = target
        self._last_applied_player = player
        self._mark_writable(player)
        self.log.append(f"mpris volume={target:.3f} player={player}")
        self.last_error = None
        return None

    def apply_pulse(self, pulse: str) -> str | None:
        """Apply mute, cycle player, or legacy up/down. Returns an error message or None."""
        if pulse not in _VOLUME_PULSES:
            return f"mpris: unknown pulse {pulse!r}"
        if self._dry_run:
            detail = f"mpris dry-run {pulse}"
            self.log.append(detail)
            self.last_error = None
            return None
        if pulse == "cycle_player":
            return self.cycle_player()
        binary = self._resolve_playerctl()
        if binary is None:
            self.last_error = "mpris: brak playerctl — głośność odtwarzacza niedostępna"
            return self.last_error
        player = self._select_player(binary)
        if player is None:
            self.last_error = self.last_error or "mpris: brak odtwarzacza MPRIS — głośność niedostępna"
            return self.last_error
        if self._volume_writable_for(player) is False and pulse != "mute":
            if not self._should_use_stream(player):
                label = self._friendly_name(player, self._cached_identity)
                self.last_error = self._volume_unwritable_message(label)
                return self.last_error
        try:
            if pulse == "volume_up":
                result = self._nudge(binary, player, +self._step)
            elif pulse == "volume_down":
                result = self._nudge(binary, player, -self._step)
            else:
                result = self._toggle_mute(binary, player)
            if result is None:
                self.reset_player()
            return result
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = f"mpris: {exc}"
            return self.last_error

    def apply_transport(self, pulse: str) -> str | None:
        """Send play-pause/next/previous via playerctl. None = success."""
        command = _TRANSPORT_PULSES.get(pulse)
        if command is None:
            return f"mpris: unknown transport {pulse!r}"
        if self._dry_run:
            detail = f"mpris dry-run {pulse}"
            self.log.append(detail)
            self.last_error = None
            return None
        binary = self._resolve_playerctl()
        if binary is None:
            return "mpris: brak playerctl"
        player = self._select_player(binary)
        if player is None:
            return self.last_error or "mpris: brak odtwarzacza dla transportu"
        try:
            err = self._exec(binary, player, [command])
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"mpris: {exc}"
        if err:
            return err
        self.log.append(f"mpris {pulse} player={player}")
        return None

    def _resolve_playerctl(self) -> str | None:
        if self._playerctl:
            return self._playerctl
        return shutil.which("playerctl")

    def cycle_player(self) -> str | None:
        """Shake gesture: pin the next MPRIS player so auto-select cannot steal it."""
        if self._dry_run:
            self.log.append("mpris dry-run cycle_player")
            self.last_error = None
            return None
        binary = self._resolve_playerctl()
        if binary is None:
            self.last_error = "mpris: brak playerctl — nie można zmienić odtwarzacza"
            return self.last_error
        players = self._list_players(binary)
        if not players:
            self._pinned_player = None
            self.last_error = "mpris: brak odtwarzacza do przełączenia"
            return self.last_error
        current = self._pinned_player if self._pinned_player in players else self._select_player(
            binary, players
        )
        index = players.index(current) if current in players else -1
        chosen = players[(index + 1) % len(players)]
        self._pinned_player = chosen
        self._cached_player = chosen
        self._last_set = None
        self._last_applied_player = None
        self._read_identity(binary, chosen)
        self.log.append(f"mpris cycle_player -> {chosen}")
        self.last_error = None
        return None

    def _player_for_volume(self, binary: str) -> str | None:
        """Reuse the last player until the rescan interval elapses."""
        if self._manual_player is not None:
            return self._select_player(binary)
        if selector_favorite(self._manual_player, "mpris") is not None:
            return self._select_player(binary)
        if (time.monotonic() - self._volume_scan_mono) < _VOLUME_RESCAN_S:
            return self._pinned_player or self._cached_player
        return self._select_player(binary)

    def _select_player(
        self, binary: str, players: tuple[str, ...] | None = None
    ) -> str | None:
        """Pick active player. A shake-pin wins until the player disappears."""
        self._volume_scan_mono = time.monotonic()
        listed = players if players is not None else self._list_players(binary)
        if self._manual_player is not None:
            favorite = selector_favorite(self._manual_player, "mpris")
            target = self._manual_player
            if favorite is not None:
                try:
                    owners = {p: self._bus_owner(p) for p in listed}
                    entries = [(p, self._desktop_entry(owner) if owner else None)
                               for p, owner in owners.items()]
                    target = unique_favorite_target(favorite, entries)
                    owner = owners[target]
                    if owner is None or self._bus_owner(target) != owner:
                        raise ValueError("favorite player bus owner changed or unavailable; refusing stale target")
                    generation = (target, owner)
                    if generation != self._favorite_generation:
                        self._invalidate_favorite_generation()
                        self._writable_players.discard(target)
                        self._unwritable_players.discard(target)
                        self._stream_players.discard(target)
                        self._favorite_generation = generation
                except ValueError as exc:
                    self._cached_player = None
                    self._invalidate_favorite_generation()
                    self.last_error = f"mpris: {exc}"
                    return None
            if target not in listed:
                self._cached_player = None
                self._manual_rebase = True
                self._manual_baseline = self._manual_origin = self._baseline_update = None
                self.last_error = f"mpris: selected player unavailable: {self._manual_player}; no substitution"
                return None
            if target != self._cached_player:
                self.reset_player()
            self._cached_player = target
            return target
        if not listed:
            self._cached_player = None
            self._pinned_player = None
            return None
        if self._pinned_player is not None and self._pinned_player not in listed:
            self._pinned_player = None
        if self._pinned_player is not None:
            self._cached_player = self._pinned_player
            return self._pinned_player
        ranked: list[tuple[tuple[int, int, int, int], str]] = []
        for index, player in enumerate(listed):
            status = self._read_status(binary, player)
            playback_rank = self._playback_rank(binary, player, status)
            writable_rank = (
                0
                if player in self._writable_players
                else (2 if player in self._unwritable_players else 1)
            )
            chromium_rank = 1 if self._looks_like_chromium_stub(player, None) else 0
            ranked.append(((playback_rank, writable_rank, chromium_rank, index), player))
        ranked.sort(key=lambda item: item[0])
        chosen = ranked[0][1]
        self._cached_player = chosen
        return chosen

    def _playback_rank(self, binary: str, player: str, status: str | None) -> int:
        """0 = live Playing, 1 = frozen Playing, then Paused/Stopped."""
        if status == "Playing":
            position = self._read_position(binary, player)
            previous = self._last_position.get(player)
            if position is not None:
                advancing = previous is None or position > previous + _STALE_POSITION_S
                self._last_position[player] = position
                return 0 if advancing else 1
            return 0
        return _STATUS_RANK.get(status or "", 3) + 1

    def _volume_writable_for(self, player: str) -> bool | None:
        if player in self._unwritable_players:
            return False
        if player in self._writable_players:
            return True
        return None

    def _mark_writable(self, player: str) -> None:
        self._writable_players.add(player)
        self._unwritable_players.discard(player)

    def _mark_unwritable(self, player: str) -> None:
        self._unwritable_players.add(player)
        self._writable_players.discard(player)

    @staticmethod
    def _is_spotify(player: str) -> bool:
        # Native Spotify MPRIS names, not a browser playing an arbitrary Spotify tab.
        return player == "spotify" or player.startswith("spotify.instance")

    def _should_use_stream(self, player: str) -> bool:
        if self._is_spotify(player):
            return True
        if player in self._stream_players:
            return True
        if self._volume_writable_for(player) is False:
            return True
        return self._looks_like_chromium_stub(player, self._cached_identity)

    def _stream_target(self, player: str) -> str:
        if selector_favorite(self._manual_player, "mpris") is not None:
            # PipeWire fallback identifies the captured owner PID/tree, never a
            # newly inherited well-known name or a fuzzy application label.
            if self._favorite_generation is not None and self._favorite_generation[0] == player:
                return self._favorite_generation[1]
            raise ValueError("favorite stream owner unavailable; no substitution")
        return player

    def _apply_stream_level(self, player: str, target: float) -> str | None:
        err = self._stream.apply_level(self._stream_target(player), target)
        if err:
            if "brak strumienia" in err:
                self.log.append(f"mpris stream pending player={player} target={target:.3f}")
                if self._is_spotify(player):
                    self.last_error = "Spotify: brak lokalnego strumienia audio. Uruchom odtwarzanie na tym komputerze; Spotify Connect na innym urządzeniu nie tworzy lokalnego strumienia."
                    return self.last_error
                self.last_error = None
                return None
            label = self._friendly_name(player, self._cached_identity)
            if self._looks_like_chromium_stub(player, self._cached_identity):
                self.last_error = f"{err}. {self._volume_unwritable_message(label)}"
                return self.last_error
            self.last_error = err
            return err
        self._stream_players.add(player)
        self._mark_unwritable(player)
        self._last_set = target
        self._last_applied_player = player
        self.log.append(f"mpris stream volume={target:.3f} player={player}")
        self.last_error = None
        return None

    def _nudge(self, binary: str, player: str, delta: float) -> str | None:
        if self._should_use_stream(player):
            current = self._stream.read_level(self._stream_target(player))
            if current is None:
                current = self._last_set if self._last_set is not None else 0.5
            return self._apply_stream_level(player, max(0.0, min(1.0, current + delta)))
        current = self._read_volume(binary, player)
        if current is None:
            suffix = f"{abs(delta):.2f}{'+' if delta > 0 else '-'}"
            err = self._exec(binary, player, ["volume", suffix])
            if err:
                self.last_error = err
                return err
            self.log.append(f"mpris volume {suffix} player={player}")
            self.last_error = None
            return None
        target = max(0.0, min(1.0, current + delta))
        err = self._exec(binary, player, ["volume", f"{target:.3f}"])
        if err:
            self.last_error = err
            return err
        verify_err = self._verify_volume(binary, player, target)
        if verify_err:
            stream_err = self._apply_stream_level(player, target)
            if stream_err is None:
                return None
            return verify_err
        if self._muted and target > 0.0:
            self._muted = False
            self._saved_volume = None
        self._last_set = target
        self._last_applied_player = player
        self._mark_writable(player)
        self.log.append(f"mpris volume {current:.3f}->{target:.3f} player={player}")
        self.last_error = None
        return None

    def _toggle_mute(self, binary: str, player: str) -> str | None:
        if self._should_use_stream(player):
            current = self._stream.read_level(self._stream_target(player))
            if self._muted or (current is not None and current <= 0.001):
                restore = self._saved_volume if self._saved_volume is not None else _DEFAULT_RESTORE
                err = self._apply_stream_level(player, restore)
                if err:
                    return err
                self._muted = False
                self.log.append(f"mpris stream unmute -> {restore:.3f} player={player}")
                return None
            saved = current if current is not None else _DEFAULT_RESTORE
            self._saved_volume = saved
            err = self._apply_stream_level(player, 0.0)
            if err:
                return err
            self._muted = True
            self.log.append(f"mpris stream mute (was {saved:.3f}) player={player}")
            return None
        if self._volume_writable_for(player) is False:
            return self.last_error or self._volume_unwritable_message(
                self._friendly_name(player, self._cached_identity)
            )
        current = self._read_volume(binary, player)
        if self._muted or (current is not None and current <= 0.001):
            restore = self._saved_volume if self._saved_volume is not None else _DEFAULT_RESTORE
            err = self._exec(binary, player, ["volume", f"{restore:.3f}"])
            if err:
                self.last_error = err
                return err
            verify_err = self._verify_volume(binary, player, restore)
            if verify_err:
                return verify_err
            self._muted = False
            self.log.append(f"mpris unmute -> {restore:.3f} player={player}")
            self.last_error = None
            return None
        saved = current if current is not None else _DEFAULT_RESTORE
        self._saved_volume = saved
        err = self._exec(binary, player, ["volume", "0.0"])
        if err:
            self.last_error = err
            return err
        verify_err = self._verify_volume(binary, player, 0.0)
        if verify_err:
            return verify_err
        self._muted = True
        self.log.append(f"mpris mute (was {saved:.3f}) player={player}")
        self.last_error = None
        return None

    def _verify_volume(self, binary: str, player: str, expected: float) -> str | None:
        actual = self._read_volume(binary, player)
        if actual is None:
            # Some players omit Volume reads after set; don't hard-fail.
            return None
        if abs(actual - expected) <= _VOLUME_VERIFY_TOLERANCE:
            self._mark_writable(player)
            return None
        self._mark_unwritable(player)
        identity = self._cached_identity
        label = self._friendly_name(player, identity)
        self.last_error = self._volume_unwritable_message(label, actual=actual, expected=expected)
        self.log.append(
            f"mpris volume verify fail expected={expected:.3f} actual={actual:.3f} player={player}"
        )
        return self.last_error

    def _read_volume(self, binary: str, player: str) -> float | None:
        if selector_favorite(self._manual_player, "mpris") is not None:
            busctl = shutil.which("busctl")
            generation = self._favorite_generation
            if busctl is None or generation is None or generation[0] != player:
                return None
            try:
                result = self._run([busctl, "--user", "get-property", generation[1],
                                    "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player",
                                    "Volume"], 1.5)
                text = (result.stdout or "").strip()
                if result.returncode != 0 or not text.startswith("d "):
                    return None
                return max(0.0, min(1.0, float(text[2:])))
            except (OSError, subprocess.TimeoutExpired, ValueError):
                return None
        try:
            result = self._run([binary, "-p", player, "volume"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        text = (result.stdout or "").strip()
        try:
            return max(0.0, min(1.0, float(text)))
        except ValueError:
            return None

    def _read_status(self, binary: str, player: str) -> str | None:
        try:
            result = self._run([binary, "-p", player, "status"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        text = (result.stdout or "").strip()
        return text or None

    def _read_position(self, binary: str, player: str) -> float | None:
        try:
            result = self._run([binary, "-p", player, "position"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        text = (result.stdout or "").strip()
        try:
            return float(text)
        except ValueError:
            return None

    def _list_players(self, binary: str) -> tuple[str, ...]:
        try:
            result = self._run([binary, "-l"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            return ()
        if result.returncode != 0:
            return ()
        lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
        return tuple(lines)

    def _read_identity(self, binary: str, player: str) -> str | None:
        """Best-effort identity. playerctl has no Identity getter; use clues."""
        self._cached_player = player
        if selector_favorite(self._manual_player, "mpris") is not None:
            generation = self._favorite_generation
            identity = self._bus_identity(generation[1]) if generation and generation[0] == player else None
            self._cached_identity = identity
            return identity
        identity: str | None = None
        player_l = player.lower()
        if "youtube" in player_l or "peardesktop" in player_l:
            identity = "com.github.th-ch.youtube-music"
        elif player_l.startswith("chromium."):
            identity = "chromium-mediasession"
        bus_identity = self._bus_identity(player)
        if bus_identity:
            identity = bus_identity
        try:
            url = self._run([binary, "-p", player, "metadata", "xesam:url"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            url = None
        if url is not None and url.returncode == 0:
            href = (url.stdout or "").strip().lower()
            if "music.youtube.com" in href:
                identity = "com.github.th-ch.youtube-music"
        self._cached_identity = identity
        return identity

    def _bus_identity(self, player: str) -> str | None:
        """Optional org.mpris.MediaPlayer2.Identity via busctl (no extra dep)."""
        busctl = shutil.which("busctl")
        if busctl is None:
            return None
        bus_name = player if player.startswith(":") else f"org.mpris.MediaPlayer2.{player}"
        try:
            result = self._run(
                [
                    busctl,
                    "--user",
                    "get-property",
                    bus_name,
                    "/org/mpris/MediaPlayer2",
                    "org.mpris.MediaPlayer2",
                    "Identity",
                ],
                1.5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        # busctl prints: s "com.github.th-ch.youtube-music"
        text = (result.stdout or "").strip()
        if text.startswith("s "):
            text = text[2:].strip()
        if len(text) >= 2 and text[0] == text[-1] == '"':
            text = text[1:-1]
        return text or None

    def _exec(self, binary: str, player: str, args: list[str]) -> str | None:
        argv = [binary, "-p", player, *args]
        if selector_favorite(self._manual_player, "mpris") is not None:
            owner = self._bus_owner(player)
            if owner is None or self._favorite_generation != (player, owner):
                self._invalidate_favorite_generation()
                return "mpris: favorite player identity changed before write; rebase required"
            busctl = shutil.which("busctl")
            if busctl is None:
                return "mpris: favorite targeted control unavailable; no substitution"
            # Unique D-Bus destination cannot be inherited by a restarted app.
            argv = [busctl, "--user", "call", owner, "/org/mpris/MediaPlayer2"]
            if len(args) == 2 and args[0] == "volume":
                argv += ["org.freedesktop.DBus.Properties", "Set", "ssv",
                         "org.mpris.MediaPlayer2.Player", "Volume", "d", args[1]]
            elif len(args) == 1 and args[0] in {"play-pause", "next", "previous"}:
                method = {"play-pause": "PlayPause", "next": "Next", "previous": "Previous"}[args[0]]
                argv += ["org.mpris.MediaPlayer2.Player", method]
            else:
                return "mpris: unsupported favorite command; no substitution"
        try:
            result = self._run(argv, 1.5)
        except subprocess.TimeoutExpired:
            return "mpris: playerctl timeout"
        except OSError as exc:
            return f"mpris: {exc}"
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "playerctl failed").strip()
            return f"mpris: {err}"
        return None

    @staticmethod
    def _looks_like_chromium_stub(player: str | None, identity: str | None) -> bool:
        player_l = (player or "").lower()
        identity_l = (identity or "").lower()
        if player_l.startswith("chromium."):
            return True
        if "youtube-music" in identity_l and "chromium" in player_l:
            return True
        return False

    @staticmethod
    def _friendly_name(player: str | None, identity: str | None) -> str:
        player_l = (player or "").lower()
        identity_l = (identity or "").lower()
        if (
            "youtube-music" in identity_l
            or "music.youtube" in identity_l
            or "peardesktop" in player_l
            or "youtube music" in identity_l
            or "pear desktop" in identity_l
        ):
            base = "Pear Desktop (YouTube Music)"
            if player_l.startswith("chromium."):
                return f"{base} / {player}"
            return f"{base}" + (f" / {player}" if player else "")
        if player_l.startswith("chromium."):
            return f"Chromium MediaSession / {player} (często Pear Desktop)"
        if player:
            return player
        if identity:
            return identity
        return "nieznany odtwarzacz"

    def _volume_unwritable_message(
        self,
        label: str,
        *,
        actual: float | None = None,
        expected: float | None = None,
    ) -> str:
        suffix = ""
        if actual is not None and expected is not None:
            suffix = f" (jest {actual:.0%}, oczekiwano {expected:.0%})"
        return (
            f"mpris: {label} nie stosuje Volume przez MPRIS{suffix}. "
            f"Transport (play/pause) może działać; next/głośność wymagają pełnego MPRIS. "
            f"Pear Desktop: Plugins → Shortcuts (& MPRIS), potem restart aplikacji. "
            f"Nie obiecujemy głośności dla aplikacji bez zapisywalnego MPRIS."
        )
