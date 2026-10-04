"""Default-sink volume while the Triki cap is inverted.

This is the only path that touches the system mixer. Upright media volume
stays on the player (MPRIS or that app's sink-input) and must never call here.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from typing import Callable

RunFn = Callable[[list[str], float], subprocess.CompletedProcess[str]]

_EPSILON = 0.008
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _default_run(argv: list[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _percent(text: str) -> float | None:
    match = _PERCENT.search(text)
    if match is None:
        return None
    return max(0.0, min(1.0, float(match.group(1)) / 100.0))


class SystemMixer:
    """Endless offset from the sink level captured when inversion starts."""

    def __init__(
        self,
        *,
        run: RunFn | None = None,
        dry_run: bool = False,
        pactl_path: str | None = None,
    ) -> None:
        self._run = run or _default_run
        self._dry_run = dry_run
        self._pactl = pactl_path
        self._baseline: float | None = None
        self._origin: float | None = None
        self._last_set: float | None = None
        self.last_error: str | None = None
        self.log: list[str] = []

    @property
    def active(self) -> bool:
        return self._baseline is not None

    def leave(self) -> None:
        """Stop adjusting the sink. The level the user set stays."""
        self._baseline = None
        self._origin = None
        self._last_set = None

    def apply_offset(self, offset: float) -> str | None:
        """Add the mapped twist to the sink level captured on entry. None = ok."""
        delta = float(offset)
        if self._baseline is None:
            level = 0.5 if self._dry_run else self.read_level()
            if level is None:
                self.last_error = "system: nie można odczytać głośności systemu"
                return self.last_error
            self._baseline = level
            self._origin = delta
            self._last_set = level
            self.last_error = None
            if self._dry_run:
                self.log.append(f"system dry-run armed baseline={level:.3f}")
            return None
        origin = 0.0 if self._origin is None else self._origin
        target = max(0.0, min(1.0, self._baseline + (delta - origin)))
        if self._last_set is not None and abs(target - self._last_set) < _EPSILON:
            return None
        if self._dry_run:
            self._last_set = target
            self.last_error = None
            self.log.append(f"system dry-run volume={target:.3f}")
            return None
        binary = self._resolve_pactl()
        if binary is None:
            self.last_error = "system: brak pactl — głośność systemu niedostępna"
            return self.last_error
        percent = int(round(target * 100))
        try:
            result = self._run(
                [binary, "set-sink-volume", "@DEFAULT_SINK@", f"{percent}%"],
                1.5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.last_error = f"system: {exc}"
            return self.last_error
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "pactl").strip()
            self.last_error = f"system: {detail}"
            return self.last_error
        self._last_set = target
        self.last_error = None
        self.log.append(f"system volume={target:.3f}")
        return None

    def read_level(self) -> float | None:
        binary = self._resolve_pactl()
        if binary is None:
            return None
        try:
            result = self._run([binary, "get-sink-volume", "@DEFAULT_SINK@"], 1.5)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if result.returncode != 0:
            return None
        return _percent(result.stdout)

    def _resolve_pactl(self) -> str | None:
        if self._pactl:
            return self._pactl
        return shutil.which("pactl")
