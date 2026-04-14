"""
DCC Character Sheet — pure business logic.

A minimal 0-level DCC character sheet. Ability score keys match CHARACTER_ABILITIES
from rulesets/dcc.py. Loads from / saves to a JSON file via marshmallow schemas;
no I/O framework dependency so it can be used by tests, CLIs, or any transport layer.
"""

import json
from pathlib import Path
from typing import cast

from rulesets.dcc import CHARACTER_ABILITIES
from models.character_sheet import CharacterSheet, CharacterSheetSchema
from models.condition import Condition  # noqa: F401 — re-exported for callers
from models.equipment import Equipment  # noqa: F401 — re-exported for callers


_schema = CharacterSheetSchema()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_sheet(path: Path) -> CharacterSheet:
    """
    Load a CharacterSheet from a JSON file.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file contains invalid JSON or schema errors.
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

    return cast(CharacterSheet, _schema.load(data))


def save_sheet(sheet: CharacterSheet, path: Path) -> None:
    """
    Persist a CharacterSheet to a JSON file.

    Raises:
        OSError: If the file cannot be written.
    """
    data = _schema.dump(sheet)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def format_sheet(sheet: CharacterSheet) -> str:
    """Return the character sheet as a human-readable string."""
    class_str = sheet.calling or "(0-level, no calling)"
    id_str = f"  [{sheet.id}]" if sheet.id else ""
    lines = [
        f"Name:       {sheet.name}{id_str}",
        f"Race:       {sheet.race}   Gender: {sheet.gender}   Alignment: {sheet.alignment}",
        f"Calling:    {class_str}  (Level {sheet.level})",
        f"Occupation: {sheet.occupation}",
        f"HP: {sheet.hp}   AC: {sheet.get_ac()}",
        "",
        "Ability Scores:",
    ]
    for ability in CHARACTER_ABILITIES:
        score = sheet.abilities.get(ability, "—")
        lines.append(f"  {ability:15s}: {score}")
    if sheet.equipment:
        lines.append("")
        lines.append("Equipment:")
        for e in sheet.equipment:
            parts = [f"x{e.quantity}" if e.quantity != 1 else ""]
            if e.weight > 0:
                parts.append(f"{e.weight} lb")
            if e.charges != -1:
                parts.append(f"{e.charges} charge(s)")
            if e.source != "starting equipment":
                parts.append(f"from: {e.source}")
            detail = "  (" + ", ".join(p for p in parts if p) + ")" if any(parts) else ""
            lines.append(f"  - {e.name}{detail}")
            for c in e.conditions:
                rounds_str = "indefinite" if c.rounds == -1 else f"{c.rounds} round(s)"
                lines.append(f"      [{c.name}] {rounds_str}")
    if sheet.conditions:
        lines.append("")
        lines.append("Conditions:")
        for c in sheet.conditions:
            rounds_str = "indefinite" if c.rounds == -1 else f"{c.rounds} round(s)"
            lines.append(f"  [{c.name}] {rounds_str} | source: {c.source}")
    lines.append("")
    lines.append("Slots:")
    for slot, e in sheet.slots.items():
        lines.append(f"  {slot:12s}: {e.name if e is not None else '—'}")
    if sheet.notes:
        lines.append("")
        lines.append("Notes:")
        lines.append("  " + "\n  ".join(sheet.notes))
    return "\n".join(lines)
