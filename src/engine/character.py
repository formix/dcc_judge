"""
Characters: 0-level party members and recruits.

Items are not stored on the character; GameState keeps every item with its one
location, which may be a character's pack, hands or worn slot.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field, fields
from typing import Any

from engine.catalog import make_item
from engine.dice import Dice
from models.item import Item
from rulesets.dcc import (
    ALIGNEMENTS,
    BIRTH_AUGURS,
    CHARACTER_ABILITIES,
    CHARACTER_OCCUPATIONS,
    CHARACTER_RACES,
    GENDERS,
    INFRAVISION_RACES,
    ZERO_LEVEL_FUNDS,
    ZERO_LEVEL_HP_DIE,
    get_ability_modifier,
    load_table,
)
from rulesets.game import result_table, table_lookup

NAMES: dict[str, list[str]] = load_table("names")["names"]


@dataclass
class Character:
    id: str
    name: str
    race: str
    gender: str
    alignment: str
    occupation: str
    trained_weapon: str
    abilities: dict[str, int]
    hp: int
    max_hp: int
    level: int = 0
    augur: dict[str, Any] = field(default_factory=dict)
    cp: int = 0
    status: str = "ok"                 # ok | fallen | dead
    fallen_at: int | None = None       # game minute when they fell
    conditions: list[dict[str, Any]] = field(default_factory=list)
    rank: str = "front"                # front | rear
    ready_to_level_up: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def infravision(self) -> bool:
        return self.race in INFRAVISION_RACES

    @property
    def active(self) -> bool:
        return self.status == "ok"

    def mod(self, ability: str) -> int:
        return get_ability_modifier(self.abilities.get(ability, 10))

    def augur_bonus(self, *applies_to: str) -> int:
        """The lucky roll modifier if the birth augur applies to any key."""
        if self.augur.get("applies_to") in applies_to:
            return int(self.augur.get("modifier", 0))
        return 0

    def condition_modifier(self, target: str, now: int) -> int:
        return sum(
            c.get("modifier", 0)
            for c in self.conditions
            if c.get("target") in (target, "all rolls") and (c.get("until") is None or c["until"] > now)
        )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: copy.deepcopy(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Character":
        return cls(**copy.deepcopy(data))


def roll_augur(dice: Dice, luck: int) -> dict[str, Any]:
    luck_mod = get_ability_modifier(luck)
    roll = max(1, min(30, dice.die(30) + luck_mod))
    name, applies_to = BIRTH_AUGURS[roll - 1]
    return {"roll": roll, "name": name, "applies_to": applies_to, "modifier": luck_mod}


COIN_VALUES = {"gp": 100, "sp": 10, "cp": 1}


def coin_value(text: str) -> int | None:
    """'4 gp, 14 sp, 27 cp' -> 541; None if the text is not money."""
    parts = re.findall(r"(\d+)\s*(gp|sp|cp)", text)
    if not parts or re.sub(r"[\d\s,]|gp|sp|cp", "", text):
        return None
    return sum(int(n) * COIN_VALUES[unit] for n, unit in parts)


def generate_character(dice: Dice, char_id: str, name: str | None = None,
                       taken: set[str] | None = None) -> tuple[Character, list[Item]]:
    """Roll a 0-level character (DCC character creation) and their starting items.

    Returns the character and the items they start with: occupation weapon,
    trade good and one random piece of equipment (Table 3-3).
    """
    races = list(CHARACTER_RACES)
    race = dice.weighted(races, [CHARACTER_RACES[r] for r in races])
    occupation, weapon, trade_good = dice.choice(CHARACTER_OCCUPATIONS[race])
    abilities = {a: dice.roll("3d6").total for a in CHARACTER_ABILITIES}
    augur = roll_augur(dice, abilities["Luck"])
    hp = dice.roll(ZERO_LEVEL_HP_DIE).total + get_ability_modifier(abilities["Stamina"])
    if augur["applies_to"] == "hp":
        hp += augur["modifier"]
    hp = max(1, hp)
    gender = dice.choice(GENDERS)
    character = Character(
        id=char_id,
        name=name or _pick_name(dice, race, taken or set()),
        race=race,
        gender=gender,
        alignment=dice.choice(ALIGNEMENTS),
        occupation=occupation,
        trained_weapon=weapon,
        abilities=abilities,
        hp=hp,
        max_hp=hp,
        augur=augur,
        cp=dice.roll(ZERO_LEVEL_FUNDS).total,
    )
    random_entry = table_lookup("starting_equipment", dice.roll(result_table("starting_equipment")["die"]).total)
    items = [make_item(weapon), make_item(random_entry["item"], random_entry.get("quantity", 1))]
    coins = coin_value(trade_good)
    if coins is None:
        items.insert(1, make_item(trade_good))
    else:
        character.cp += coins
    return character, items


def _pick_name(dice: Dice, race: str, taken: set[str]) -> str:
    pool = [n for n in NAMES.get(race, NAMES["Human"]) if n not in taken] or NAMES["Human"]
    return dice.choice(pool)
