"""Persist the preferred multimedia source used by the configurator preview."""

from __future__ import annotations

import json
import os
from pathlib import Path

_PREF_FILENAME = "media-player.json"


def default_media_preferences_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "triki-controller" / _PREF_FILENAME


def load_default_player(path: Path | None = None) -> str | None:
    target = path or default_media_preferences_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("default_player")
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def save_default_player(player: str | None, path: Path | None = None) -> Path:
    target = path or default_media_preferences_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    value = None if player is None else player.strip() or None
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"default_player": value}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, target)
    return target
