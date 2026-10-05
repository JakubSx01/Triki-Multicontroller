"""Validated stable application descriptors, separate from ephemeral player IDs.

Selectors are internal backend tokens; public player lists retain (id, label).
Exact native app identities only: never infer identities from display names.
"""
from __future__ import annotations

import json
from collections.abc import Mapping

_PREFIX = "triki-favorite:"


def parse_media_favorite(value: object) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"platform", "app_id", "label"}:
        raise ValueError("media_favorite: expected platform, app_id and label")
    if any(not isinstance(v, str) or not v.strip() for v in value.values()):
        raise ValueError("media_favorite: fields must be nonempty strings")
    if value["platform"] not in {"windows", "macos", "mpris"}:
        raise ValueError("media_favorite: unsupported platform")
    return dict(value)


def favorite_selector(value: Mapping[str, str]) -> str:
    return _PREFIX + json.dumps(parse_media_favorite(value), sort_keys=True)


def selector_favorite(player: str | None, platform: str) -> dict[str, str] | None:
    if player is None or not player.startswith(_PREFIX):
        return None
    descriptor = parse_media_favorite(json.loads(player[len(_PREFIX):]))
    if descriptor is None or descriptor["platform"] != platform:
        raise ValueError("media_favorite: target belongs to another platform")
    return descriptor


def unique_favorite_target(descriptor: Mapping[str, str], candidates: list[tuple[str, str]]) -> str:
    matches = {key for key, app_id in candidates if app_id == descriptor["app_id"]}
    if len(matches) != 1:
        problem = "ambiguous" if matches else "unavailable"
        raise ValueError(f"favorite player {problem}: {descriptor['label']}; no substitution")
    return next(iter(matches))
