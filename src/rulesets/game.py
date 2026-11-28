"""
Rules of this game, loaded from data/tables/ (see docs/design.md).

DCC rules live in rulesets/dcc.py; this module holds the game's own rules and
the result tables (critical hits, fumbles, starting equipment).
"""

from functools import lru_cache

from rulesets.dcc import load_table

RULES: dict = load_table("game_rules")
MATERIALS: dict[str, dict] = load_table("materials")["materials"]
ITEM_RULES: dict = load_table("item_rules")

PERCEPTION_MODES = ("light", "infravision", "touch")


@lru_cache(maxsize=None)
def result_table(name: str) -> dict:
    """Load a range table (critical, fumble or items) and check its ranges."""
    table = load_table(name)
    entries = table["entries"]
    for i, entry in enumerate(entries):
        if i > 0 and "min" not in entry:
            raise ValueError(f"{name}: entry {i} needs 'min'")
        if i < len(entries) - 1 and "max" not in entry:
            raise ValueError(f"{name}: entry {i} needs 'max'")
        if i > 0 and entry["min"] != entries[i - 1]["max"] + 1:
            raise ValueError(f"{name}: gap or overlap before entry {i}")
    return table


def table_lookup(name: str, roll: int) -> dict:
    """Return the entry of a range table matching a final roll."""
    for entry in result_table(name)["entries"]:
        low = entry.get("min", -10_000)
        high = entry.get("max", 10_000)
        if low <= roll <= high:
            return entry
    raise ValueError(f"{name}: no entry for {roll}")


def material(name: str) -> dict:
    return MATERIALS.get(name, MATERIALS["misc"])


def light_stage(minutes_left: int) -> str:
    for band in RULES["light_stages"]:
        if minutes_left <= band["max"]:
            return band["stage"]
    return "bright"
