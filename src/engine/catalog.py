"""
Catalog: turns the DCC equipment tables into Items with named rules.

Weapon and armor statistics become `weapon` and `armor` rules. Other rules and
materials come from data/tables/item_rules.yaml.
"""

from __future__ import annotations

import copy
import re

from models import Equipment
from models.item import Item
from rulesets.dcc import AMMUNITIONS, ARMORS, GEAR, WEAPONS
from rulesets.game import ITEM_RULES


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _same_text(name: str) -> dict[str, str]:
    """Things a character carries are known in every perception mode."""
    return {"light": name, "infravision": name, "touch": name}


def _weapon_rule(e: Equipment) -> dict:
    rule: dict = {"damage": e.damage}
    if "two-handed" in e.tags:
        rule["two_handed"] = True
    if "melee" in e.tags:
        rule["melee"] = True
    if "ranged" in e.tags:
        rule["ranged"] = True
        rule["ranges"] = list(e.ranges)
    if "reach" in e.tags:
        rule["reach"] = True
    if e.backstab:
        rule["backstab"] = e.backstab
    return rule


def _armor_rule(e: Equipment) -> dict:
    rule: dict = {"ac": 0, "slot": "body"}
    for c in e.conditions:
        if c.target == "ac":
            rule["ac"] = c.modifier
        elif c.target in ("check_penalty", "speed"):
            rule[c.target] = c.modifier
    if e.fumble:
        rule["fumble"] = e.fumble
    if "shield" in e.tags:
        rule["slot"] = "shield"
    elif "head" in e.tags:
        rule["slot"] = "head"
    return rule


def _from_equipment(e: Equipment, kind: str) -> Item:
    rules: dict = {}
    if kind == "weapon":
        rules["weapon"] = _weapon_rule(e)
    elif kind == "armor":
        rules["armor"] = _armor_rule(e)
    rules.update(copy.deepcopy(ITEM_RULES["rules"].get(e.name, {})))
    material = ITEM_RULES["materials"].get(e.name, ITEM_RULES["default_material"].get(kind, "misc"))
    return Item(
        id=slug(e.name),
        name=_same_text(e.name),
        description=_same_text(e.name),
        material=material,
        rules=rules,
        notes=e.note or "",
        cost_cp=e.cost_cp,
    )


def _build() -> dict[str, Item]:
    catalog: dict[str, Item] = {}
    for kind, items in (("weapon", WEAPONS), ("armor", ARMORS), ("gear", GEAR), ("gear", AMMUNITIONS)):
        for e in items:
            if "immaterial" in e.tags:
                continue
            catalog.setdefault(e.name.lower(), _from_equipment(e, kind))
    return catalog


CATALOG: dict[str, Item] = _build()


def catalog_item(name: str) -> Item | None:
    """Return a fresh copy of a catalog item by name (case-insensitive)."""
    item = CATALOG.get(name.lower())
    return item.copy() if item else None


def make_item(name: str, quantity: int = 1) -> Item:
    """A catalog item, or a plain item for trade goods the catalog lacks."""
    item = catalog_item(name)
    if item is None:
        item = Item(id=slug(name), name=_same_text(name), description=_same_text(name))
    item.quantity = quantity
    if item.rules.get("light", {}).get("starts_empty"):
        item.state["remaining"] = 0
    elif "light" in item.rules:
        item.state["remaining"] = item.rules["light"]["minutes"]
    return item
