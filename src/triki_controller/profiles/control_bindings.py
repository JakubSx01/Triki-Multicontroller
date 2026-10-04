"""Platform-independent control vocabulary and strict sparse overlays.

Missing entries and ``default`` preserve legacy behavior; ``off`` suppresses
that source. A remapped held button suppresses legacy mouse clicks, but explicit
click/double/triple bindings still run after the existing quiet window.
"""
from __future__ import annotations

from typing import Mapping

BINDING_PROFILES = ("steering", "mouse", "plane")
BINDING_SOURCES = ("button", "click", "double_click", "triple_click", "left", "right", "forward", "backward")
KEY_ACTIONS = (
    *(f"key_{letter}" for letter in "abcdefghijklmnopqrstuvwxyz"),
    *(f"key_{digit}" for digit in "0123456789"),
    "key_up", "key_down", "key_left", "key_right", "key_space", "key_enter",
    "key_escape", "key_shift", "key_ctrl", "key_alt", "key_tab", "key_backspace",
)
BINDING_ACTIONS = ("default", "off", "mouse_left", "mouse_right", "mouse_middle", *KEY_ACTIONS)


def parse_control_bindings(raw: object, errors: list[str] | None = None) -> dict[str, dict[str, str]]:
    """Validate and copy a sparse overlay; raise unless collecting settings errors."""
    issues: list[str] = []
    result: dict[str, dict[str, str]] = {}
    if not isinstance(raw, Mapping):
        issues.append("control_bindings: must be an object keyed by profile")
    else:
        for profile, entries in raw.items():
            if profile not in BINDING_PROFILES:
                issues.append(f"control_bindings: unknown profile {profile!r}")
                continue
            if not isinstance(entries, Mapping):
                issues.append(f"control_bindings.{profile}: must be an object")
                continue
            parsed: dict[str, str] = {}
            for source, action in entries.items():
                if source not in BINDING_SOURCES:
                    issues.append(f"control_bindings.{profile}: unknown source {source!r}")
                elif not isinstance(action, str) or action not in BINDING_ACTIONS:
                    issues.append(f"control_bindings.{profile}.{source}: unknown action {action!r}")
                else:
                    parsed[source] = action
            result[profile] = parsed
    if errors is not None:
        errors.extend(issues)
    elif issues:
        raise ValueError("; ".join(issues))
    return result
