"""
DCC Character Sheet — pure business logic.

A minimal 0-level DCC character sheet. Ability score keys match DCC_ABILITIES
from dice_service.py. Loads from / saves to a JSON file; no I/O framework
dependency so it can be used by tests, CLIs, or any transport layer.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from services.dice_service import DCC_ABILITIES

# JSON file in the working directory (project root when run normally).
DEFAULT_SHEET_PATH = Path("character.json")


@dataclass
class CharacterSheet:
    name: str = "Unknown Hero"
    occupation: str = "Peasant"
    abilities: dict[str, int] = field(
        default_factory=lambda: {a: 10 for a in DCC_ABILITIES}
    )
    hp: int = 4
    ac: int = 10
    equipment: list[str] = field(default_factory=list)


def load_sheet(path: Path = DEFAULT_SHEET_PATH) -> CharacterSheet:
    """
    Load a CharacterSheet from a JSON file.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If required fields are missing or malformed.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"No character sheet found at '{path}'. "
            "Create a character.json in the project root."
        )
    try:
        data: dict = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in '{path}': {exc}") from exc

    return CharacterSheet(
        name=data.get("name", "Unknown Hero"),
        occupation=data.get("occupation", "Peasant"),
        abilities=data.get("abilities", {a: 10 for a in DCC_ABILITIES}),
        hp=int(data.get("hp", 4)),
        ac=int(data.get("ac", 10)),
        equipment=list(data.get("equipment", [])),
    )


def format_sheet(sheet: CharacterSheet) -> str:
    """Return the character sheet as a human-readable string."""
    lines = [
        f"Name:       {sheet.name}",
        f"Occupation: {sheet.occupation}",
        f"HP: {sheet.hp}   AC: {sheet.ac}",
        "",
        "Ability Scores:",
    ]
    for ability in DCC_ABILITIES:
        score = sheet.abilities.get(ability, "—")
        lines.append(f"  {ability:15s}: {score}")
    if sheet.equipment:
        lines.append("")
        lines.append("Equipment:")
        for item in sheet.equipment:
            lines.append(f"  - {item}")
    return "\n".join(lines)
