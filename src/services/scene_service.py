"""
DCC Scene Manager — pure business logic.

Maintains the in-memory party of 0-level characters for a DCC funnel session.
State lives for the duration of the process; nothing is written to disk.
"""

import random
import uuid

from rulesets.dcc import CHARACTER_RACES, CHARACTER_OCCUPATIONS, CHARACTER_ABILITIES, ABILITY_MODIFIERS
from services.character_service import CharacterSheet, Equipment, Condition

# ---------------------------------------------------------------------------
# Party state (in-memory singleton)
# ---------------------------------------------------------------------------

_party: list[CharacterSheet] = []

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _roll_die(sides: int) -> int:
    return random.randint(1, sides)


def _roll_many(sides: int, count: int) -> list[int]:
    return [_roll_die(sides) for _ in range(count)]


def _random_race() -> str:
    races = list(CHARACTER_RACES.keys())
    weights = list(CHARACTER_RACES.values())
    return random.choices(races, weights=weights, k=1)[0]


def _random_occupation(race: str) -> tuple[str, str, str]:
    return random.choice(CHARACTER_OCCUPATIONS[race])


def _generate_character(name: str) -> CharacterSheet:
    race = _random_race()
    occ_name, weapon, trade_good = _random_occupation(race)

    # Non-humans use their race as their calling; humans start uncalled.
    calling = race if race != "Human" else None

    # Ability scores: 3d6 straight for each attribute.
    abilities = {a: sum(_roll_many(6, 3)) for a in CHARACTER_ABILITIES}

    # 0-level HP: 1d4 + Stamina modifier (minimum 1).
    stamina_mod = ABILITY_MODIFIERS.get(abilities["Stamina"], 0)
    hp = max(1, _roll_die(4) + stamina_mod)

    # Starting equipment comes from the occupation table.
    equipment = [
        Equipment(name=weapon,     source="starting equipment"),
        Equipment(name=trade_good, source="starting equipment"),
    ]

    return CharacterSheet(
        id=str(uuid.uuid4())[:8],
        name=name,
        occupation=occ_name,
        race=race,
        calling=calling,
        level=0,
        abilities=abilities,
        hp=hp,
        ac=10,
        equipment=equipment,
        conditions=[],
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_party(n: int = 4) -> list[CharacterSheet]:
    """Generate N random 0-level characters with placeholder names."""
    global _party
    _party = [_generate_character(f"Character_{i + 1}") for i in range(n)]
    return list(_party)


def get_party() -> list[CharacterSheet]:
    """Return the current party."""
    return list(_party)


def get_party_stubs() -> list[dict]:
    """
    Return a minimal descriptor for each party member as a list of dicts
    with keys: id, race, occupation.
    """
    return [{"id": ch.id, "race": ch.race, "occupation": ch.occupation} for ch in _party]


def get_character_by_id(character_id: str) -> CharacterSheet | None:
    """Return the character with the given short ID, or None."""
    for ch in _party:
        if ch.id == character_id:
            return ch
    return None


def get_character(name: str) -> CharacterSheet | None:
    """Return the character with the given name (case-insensitive), or None."""
    name_lower = name.lower()
    for ch in _party:
        if ch.name.lower() == name_lower:
            return ch
    return None


def rename_character(character_id: str, new_name: str) -> CharacterSheet:
    """
    Set a character's name by their ID.

    Raises:
        KeyError: If no character with that ID exists in the party.
    """
    ch = get_character_by_id(character_id)
    if ch is None:
        raise KeyError(f"No character with id '{character_id}' in party.")
    ch.name = new_name
    return ch


def update_hp(name: str, delta: int) -> CharacterSheet:
    """
    Adjust a party member's HP by *delta*.

    Raises:
        KeyError: If name is not found in the party.
    """
    ch = get_character(name)
    if ch is None:
        raise KeyError(f"Character '{name}' not found in party.")
    ch.hp += delta
    return ch


def add_condition(name: str, condition: Condition) -> CharacterSheet:
    """
    Append a condition to a party member's condition list.

    Raises:
        KeyError: If name is not found in the party.
    """
    ch = get_character(name)
    if ch is None:
        raise KeyError(f"Character '{name}' not found in party.")
    ch.conditions.append(condition)
    return ch


def remove_condition(name: str, condition_name: str) -> tuple[CharacterSheet, int]:
    """
    Remove all conditions matching *condition_name* (case-insensitive) from a
    party member.

    Returns:
        (character, number_removed)

    Raises:
        KeyError: If the character name is not found in the party.
    """
    ch = get_character(name)
    if ch is None:
        raise KeyError(f"Character '{name}' not found in party.")
    before = len(ch.conditions)
    ch.conditions = [c for c in ch.conditions if c.name.lower() != condition_name.lower()]
    return ch, before - len(ch.conditions)


def format_party() -> str:
    """Return a human-readable summary of the entire party."""
    if not _party:
        return "The party is empty."
    lines = [f"Party — {len(_party)} adventurer(s):", ""]
    for ch in _party:
        calling_str = ch.calling or "none (0-level funnel)"
        lines.append(f"  {ch.name}")
        lines.append(f"    Race: {ch.race}   Occupation: {ch.occupation}   Calling: {calling_str}")
        lines.append(f"    HP: {ch.hp}   AC: {ch.ac}   Level: {ch.level}")
        ab_str = "  ".join(f"{k[:3]}:{v}" for k, v in ch.abilities.items())
        lines.append(f"    {ab_str}")
        if ch.equipment:
            items = ", ".join(e.name for e in ch.equipment)
            lines.append(f"    Equipment: {items}")
        if ch.conditions:
            conds = ", ".join(c.name for c in ch.conditions)
            lines.append(f"    Conditions: {conds}")
        lines.append("")
    return "\n".join(lines)
