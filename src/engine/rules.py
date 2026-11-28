"""
Checks, saving throws and perception (docs/design.md 6.3 and 11; DCC rules).

Every result is a dict with the die, the roll, the modifier, the total, success
and a short text for the event log.
"""

from __future__ import annotations

from typing import Any

from engine.character import Character
from engine.dice import step_die
from rulesets.dcc import SAVE_ABILITIES
from rulesets.game import RULES

PHYSICAL = ("Strength", "Agility")


def _result(char: Character, what: str, die: int, roll: int, mod: int, dc: int) -> dict[str, Any]:
    total = roll + mod
    success = total >= dc
    return {
        "character": char.id, "what": what, "die": die, "roll": roll, "modifier": mod,
        "total": total, "dc": dc, "success": success,
        "text": f"{char.name}, {what}: d{die} {roll}{mod:+d} = {total} vs {dc}, {'success' if success else 'failure'}",
    }


def check_die(world, char: Character, occupation_applies: bool) -> int:
    """Occupation rule: d20 when the occupation applies, d10 otherwise; darkness steps it down."""
    base = 20 if occupation_applies else 10
    return step_die(base, RULES["vision"][world.mode_for(char)]["die_steps"])


def ability_check(world, char: Character, ability: str, dc: int, occupation_applies: bool = False) -> dict[str, Any]:
    die = check_die(world, char, occupation_applies)
    mod = char.mod(ability) + char.augur_bonus("skill_checks") + char.condition_modifier("checks", world.now)
    if ability in PHYSICAL:
        mod += world.armor_check_penalty(char)
    return _result(char, f"{ability} check", die, world.dice.die(die), mod, dc)


def perception_check(world, char: Character, dc: int, kind: str = "search") -> dict[str, Any]:
    """Searching and noticing: the die depends only on what the character can see."""
    die = RULES["vision"][world.mode_for(char)]["perception_die"]
    mod = char.mod(RULES["perception_ability"]) + char.condition_modifier("checks", world.now)
    if kind == "secret_door":
        mod += char.augur_bonus("find_secret_doors")
    elif kind == "trap":
        mod += char.augur_bonus("find_traps")
    return _result(char, "perception", die, world.dice.die(die), mod, dc)


def saving_throw(world, char: Character, save: str, dc: int, trap: bool = False) -> dict[str, Any]:
    save = save.lower()
    ability = SAVE_ABILITIES[save]
    mod = char.mod(ability) + char.augur_bonus("saves", save) + char.condition_modifier("saves", world.now)
    if trap:
        mod += char.augur_bonus("trap_saves")
    return _result(char, f"{save.capitalize()} save", 20, world.dice.die(20), mod, dc)


def luck_check(world, char: Character) -> dict[str, Any]:
    """Roll at or under Luck (used to recover the body)."""
    die = RULES["recover_body_die"]
    roll = world.dice.die(die)
    luck = char.abilities["Luck"]
    success = roll <= luck
    return {"character": char.id, "what": "Luck check", "die": die, "roll": roll, "dc": luck,
            "success": success,
            "text": f"{char.name}, Luck check: d{die} {roll} vs Luck {luck}, {'success' if success else 'failure'}"}


def least_stealthy(world) -> Character:
    """Group silence uses the member worst at moving quietly (design 11)."""
    ability = RULES["silence"]["ability"]
    return min(world.state.active(), key=lambda c: c.mod(ability) + world.armor_check_penalty(c))


def silence_check(world, occupation_applies: bool = False, dc: int | None = None) -> dict[str, Any]:
    char = least_stealthy(world)
    result = ability_check(world, char, RULES["silence"]["ability"], dc or RULES["silence"]["dc"], occupation_applies)
    result["text"] = "Moving quietly: " + result["text"]
    return result
