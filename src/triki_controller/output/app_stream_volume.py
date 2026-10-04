"""Per-application PipeWire/Pulse sink-input volume (not the system mixer).

Pear Desktop / Chromium MediaSession expose MPRIS Volume that does not change.
The process still has a sink-input we can set. Never touches the default sink.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable

RunFn = Callable[[list[str], float], subprocess.CompletedProcess[str]]
PpidFn = Callable[[int], int | None]


def _default_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _read_ppid(pid: int) -> int | None:
    try:
        text = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def _volume_from_channels(volume: object) -> float | None:
    if not isinstance(volume, dict) or not volume:
        return None
    values: list[float] = []
    for channel in volume.values():
        if not isinstance(channel, dict):
            continue
        raw = channel.get("value")
        if isinstance(raw, (int, float)):
            values.append(float(raw) / 65536.0)
    if not values:
        return None
    return max(0.0, min(1.0, sum(values) / len(values)))


class AppStreamVolume:
    """Set/read Pulse sink-input volume for an MPRIS player's process tree."""

    def __init__(
        self,
        *,
        run: RunFn | None = None,
        read_ppid: PpidFn | None = None,
        pactl_path: str | None = None,
        busctl_path: str | None = None,
    ) -> None:
        self._run = run or _default_run
        self._read_ppid = read_ppid or _read_ppid
        self._pactl = pactl_path
        self._busctl = busctl_path

    def read_level(self, player: str) -> float | None:
        indexes = self._sink_indexes(player)
        if not indexes:
            return None
        inputs = self._list_sink_inputs()
        levels = [item[2] for item in inputs if item[0] in indexes and item[2] is not None]
        if not levels:
            return None
        return sum(levels) / len(levels)

    def apply_level(self, player: str, level: float) -> str | None:
        target = max(0.0, min(1.0, float(level)))
        indexes = self._sink_indexes(player)
        if not indexes:
            return "stream: brak strumienia audio aplikacji"
        binary = self._resolve_pactl()
        if binary is None:
            return "stream: brak pactl"
        percent = int(round(target * 100))
        for index in indexes:
            try:
                result = self._run(
                    [binary, "set-sink-input-volume", str(index), f"{percent}%"],
                    1.5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return f"stream: {exc}"
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "pactl failed").strip()
                return f"stream: {err}"
        actual = self.read_level(player)
        if actual is None:
            return None
        if abs(actual - target) > 0.06:
            return (
                f"stream: głośność aplikacji nie zmieniła się "
                f"(jest {actual:.0%}, oczekiwano {target:.0%})"
            )
        return None

    def apply_mute(self, player: str, muted: bool) -> str | None:
        indexes = self._sink_indexes(player)
        if not indexes:
            return "stream: brak strumienia audio aplikacji"
        binary = self._resolve_pactl()
        if binary is None:
            return "stream: brak pactl"
        flag = "1" if muted else "0"
        for index in indexes:
            try:
                result = self._run(
                    [binary, "set-sink-input-mute", str(index), flag],
                    1.5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return f"stream: {exc}"
            if result.returncode != 0:
                err = (result.stderr or result.stdout or "pactl failed").strip()
                return f"stream: {err}"
        return None

    def _sink_indexes(self, player: str) -> tuple[int, ...]:
        owner = self._owner_pid(player)
        if owner is None:
            return ()
        found: list[int] = []
        for index, pid, _level in self._list_sink_inputs():
            if pid is None:
                continue
            if self._in_tree(pid, owner):
                found.append(index)
        return tuple(found)

    def _in_tree(self, pid: int, ancestor: int) -> bool:
        if pid == ancestor:
            return True
        current = pid
        seen: set[int] = set()
        for _ in range(12):
            if current in seen or current <= 1:
                return False
            seen.add(current)
            parent = self._read_ppid(current)
            if parent is None or parent <= 1:
                return False
            if parent == ancestor:
                return True
            current = parent
        return False

    def _owner_pid(self, player: str) -> int | None:
        busctl = self._busctl or shutil.which("busctl")
        if busctl is None:
            return None
        bus_name = f"org.mpris.MediaPlayer2.{player}"
        try:
            result = self._run(
                [
                    busctl,
                    "--user",
                    "call",
                    "org.freedesktop.DBus",
                    "/org/freedesktop/DBus",
                    "org.freedesktop.DBus",
                    "GetConnectionUnixProcessID",
                    "s",
                    bus_name,
                ],
                1.5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        text = (result.stdout or "").strip()
        parts = text.split()
        if not parts:
            return None
        try:
            return int(parts[-1])
        except ValueError:
            return None

    def _list_sink_inputs(self) -> list[tuple[int, int | None, float | None]]:
        binary = self._resolve_pactl()
        if binary is None:
            return []
        try:
            result = self._run([binary, "--format=json", "list", "sink-inputs"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        items: list[tuple[int, int | None, float | None]] = []
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            if not isinstance(index, int):
                continue
            props = entry.get("properties") or {}
            raw_pid = props.get("application.process.id") if isinstance(props, dict) else None
            pid: int | None
            try:
                pid = int(raw_pid) if raw_pid is not None else None
            except (TypeError, ValueError):
                pid = None
            items.append((index, pid, _volume_from_channels(entry.get("volume"))))
        return items

    def _resolve_pactl(self) -> str | None:
        if self._pactl:
            return self._pactl
        return shutil.which("pactl")
