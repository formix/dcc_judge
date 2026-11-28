"""
DCC ruleset: tables and rule constants.

Tables live as YAML in data/tables/ and are loaded here under their historical
Python names, so callers keep importing them from this module. Rule constants
(dice, durations, thresholds) stay in Python below.

Sources: the public DCC compendium at https://roll20.net/compendium/dcc/,
cited per table in each YAML file.
"""

from pathlib import Path

import yaml

from models import Equipment
from models.equipment import EquipmentSchema

TABLES_DIR = Path(__file__).resolve().parents[2] / "data" / "tables"


def load_table(name: str) -> dict:
    """Load data/tables/<name>.yaml."""
    with open(TABLES_DIR / f"{name}.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _equipment(name: str) -> list[Equipment]:
    schema = EquipmentSchema()
    return [schema.load(entry) for entry in load_table(name)["items"]]


_races = load_table("races")["races"]
_character = load_table("character")

# Playable races and the chance of rolling each for a 0-level character.
CHARACTER_RACES: dict[str, float] = {r: v["weight"] for r, v in _races.items()}
# Base speed in feet.
RACE_SPEED: dict[str, int] = {r: v["speed"] for r, v in _races.items()}
# Races with infravision.
INFRAVISION_RACES: set[str] = {r for r, v in _races.items() if v["infravision"]}

# Each race maps to a list of (occupation, trained_weapon, trade_good) tuples.
CHARACTER_OCCUPATIONS: dict[str, list[tuple[str, str, str]]] = {
    race: [(o["occupation"], o["weapon"], o["trade_good"]) for o in occs]
    for race, occs in load_table("occupations")["occupations"].items()
}

WEAPONS: list[Equipment] = _equipment("weapons")
AMMUNITIONS: list[Equipment] = _equipment("ammunition")
ARMORS: list[Equipment] = _equipment("armor")
GEAR: list[Equipment] = _equipment("gear")
MOUNT_GEAR: list[Equipment] = _equipment("mount_gear")

CHARACTER_CLASSES: list[str] = _character["classes"]
ALIGNEMENTS: list[str] = _character["alignments"]
GENDERS: list[str] = _character["genders"]
# Worn-equipment slots.
SLOTS: list[str] = _character["slots"]
# The full DCC dice chain, weakest to strongest.
DICE_CHAIN: list[int] = _character["dice_chain"]
CHARACTER_ABILITIES: list[str] = _character["abilities"]
# Table 1-1: ability score modifiers.
ABILITY_MODIFIERS: dict[int, int] = {int(k): v for k, v in _character["ability_modifiers"].items()}
# Saving throw -> ability at 0 level.
SAVE_ABILITIES: dict[str, str] = _character["saves"]

# Table 1-2: birth augur and lucky roll, as (augur name, what it applies to).
BIRTH_AUGURS: list[tuple[str, str]] = [
    (e["name"], e["applies_to"]) for e in load_table("birth_augurs")["entries"]
]

# Table 4-1: attack roll modifiers, as (melee, missile).
ATTACK_MODIFIERS: dict[str, tuple] = {
    k: tuple(v) for k, v in load_table("attack_modifiers")["modifiers"].items()
}


def get_ability_modifier(score: int) -> int:
    """
    Return the DCC ability modifier for a score (Table 1-1).

    Scores below 1 return -128 (no meaningful modifier). Scores of 1-2 use the
    score-3 modifier and scores above 18 use the score-18 modifier, since the
    table only covers 3-18.
    """
    if score < 1:
        return -128
    return ABILITY_MODIFIERS[min(max(score, 3), 18)]


# ── Rule constants ───────────────────────────────────────────────────────────

# Hit points at 0 level: 1d4 + Stamina modifier (minimum 1).
ZERO_LEVEL_HP_DIE = "1d4"
# Starting funds at 0 level.
ZERO_LEVEL_FUNDS = "5d12"   # copper pieces

# ── Combat (https://roll20.net/compendium/dcc/Combat) ────────────────────────
# Initiative: 1d20 + Agility modifier, once per encounter; d16 with a
# two-handed weapon.
INITIATIVE_DIE = 20
TWO_HANDED_INITIATIVE_DIE = 16
# Natural 20 is a critical hit (always hits); natural 1 is a fumble (always
# misses). 0-level characters roll 1d4 on Crit Table I, adjusted by Luck.
ZERO_LEVEL_CRIT_DIE = 4
ZERO_LEVEL_CRIT_TABLE = "crit_table_i"
# The fumble roll is adjusted by the reverse of the Luck modifier.
UNARMORED_FUMBLE_DIE = "d4"
# A successful attack always does at least 1 damage.
MINIMUM_DAMAGE = 1
# 0-level characters are trained in their occupation weapon; the -1d penalty
# for untrained weapons is waived at 0 level.
UNTRAINED_WEAPON_DIE_STEPS = -1
UNTRAINED_PENALTY_WAIVED_AT_LEVEL_0 = True

# Firing into melee: on a miss, 50% chance to hit a random ally in the melee.
MISSILE_INTO_MELEE_FRIENDLY_FIRE = 0.5

# Recovering the body: an ally who reaches the body within an hour rolls the
# fallen character over; the fallen character makes a Luck check. Success:
# 1 HP, groggy for an hour (-4 to all rolls), and -1 to a random one of
# Strength, Agility or Stamina, permanently.
RECOVER_BODY_WINDOW_MINUTES = 60
RECOVER_BODY_GROGGY_MINUTES = 60
RECOVER_BODY_GROGGY_PENALTY = -4
RECOVER_BODY_ABILITY_LOSS = ("Strength", "Agility", "Stamina")

# Natural healing: 1 HP per good night's rest while adventuring, 2 HP per day
# of bed rest. Never above maximum. Ability loss heals at the same rate except
# Luck, which does not heal.
HEAL_NIGHT_REST = 1
HEAL_BED_REST_DAY = 2

# Burning Luck: any character may spend Luck points for an equal one-time
# bonus on one of their own rolls, before or after rolling. Lost Luck does not
# heal. Only warriors and dwarves may burn 1 Luck to cancel a fumble.

# ── Equipment (https://roll20.net/compendium/dcc/Rules:Equipment) ────────────
# One flask of oil burns for 6 hours in a lantern. Thrown burning oil: 1d6
# damage plus fire; DC 10 Reflex save to put it out, else 1d6 more each round.
LANTERN_MINUTES_PER_OIL_FLASK = 360
THROWN_OIL_DAMAGE = "1d6"
THROWN_OIL_SAVE_DC = 10
# Lighting a torch or lantern takes one action.
