"""
Encounter level and wandering encounter tables (docs/design.md 10 and 10.1).

The encounter level is a d6 range: level 2 means an encounter on 1-2. It
carries over between actions. `apply_level_events` is pure so it can also be
served on its own.

Events:
    loud                  +1
    silent                -1, not below the starting level
    dark_10               +1 per full 10 minutes in darkness
    quiet_light_10        -1 per full 10 minutes in light without loud actions
"""

from __future__ import annotations

from rulesets.game import RULES

_RULES = RULES["encounter_level"]
EVENT_CHANGES = {
    "loud": _RULES["loud"],
    "silent": _RULES["silent"],
    "dark_10": _RULES["dark_per_10_minutes"],
    "quiet_light_10": _RULES["quiet_light_per_10_minutes"],
}


def apply_level_events(level: int, start: int, events: list[str]) -> int:
    """Return the new encounter level after the events, in order."""
    top = max(_RULES["max"], start)
    for event in events:
        if event not in EVENT_CHANGES:
            raise ValueError(f"Unknown encounter event '{event}'")
        level = max(start, min(top, level + EVENT_CHANGES[event]))
    return level


def pick_encounter(dice, table: list[dict], spent: dict[str, int]) -> dict | None:
    """Choose a weighted entry, skipping entries that have reached their limit."""
    available = [e for e in table if spent.get(e["id"], 0) < e.get("limit", 1_000_000)]
    if not available:
        return None
    return dice.weighted(available, [e.get("weight", 1) for e in available])
