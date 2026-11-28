"""
GameState: everything a save holds (docs/design.md 12.3).

The original adventure is never modified. Fixed scene objects are changed
through per-scene change lists; portable items live in `items` with exactly one
location each in `locations`:

    {"scene": scene_id}
    {"char": character_id, "slot": "pack" | "hands" | "worn"}
"""

from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from engine.character import Character
from models.item import Item

SAVE_VERSION = 1
# Saves and logs go under DCC_JUDGE_DATA_DIR if set, else the project folder.
DATA_DIR = Path(os.environ.get("DCC_JUDGE_DATA_DIR") or Path(__file__).resolve().parents[2])
SAVES_DIR = DATA_DIR / "saves"


@dataclass
class GameState:
    adventure_id: str
    scene: str
    adventure_source: str = ""           # file path or URL the adventure was loaded from
    version: int = SAVE_VERSION
    turn: int = 0
    clock: int = 0                       # game minutes since the adventure began
    phase: str = "exploration"           # exploration | combat | over
    outcome: str | None = None           # None | lost | won
    visited: list[str] = field(default_factory=list)
    characters: list[Character] = field(default_factory=list)
    leader: str = ""
    items: dict[str, Item] = field(default_factory=dict)
    locations: dict[str, dict[str, str]] = field(default_factory=dict)
    scene_changes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    discovered: list[str] = field(default_factory=list)
    flags: dict[str, Any] = field(default_factory=dict)
    encounter: dict[str, int] = field(default_factory=dict)  # level, start, carry, dark, quiet
    spent_encounters: dict[str, int] = field(default_factory=dict)
    groups: dict[str, dict[str, Any]] = field(default_factory=dict)
    combat: dict[str, Any] | None = None
    rulings: dict[str, Any] = field(default_factory=dict)
    facts: list[str] = field(default_factory=list)
    timers: list[dict[str, Any]] = field(default_factory=list)
    adventure_rules: list[dict[str, Any]] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)
    pending: dict[str, Any] | None = None
    deadline_fired: bool = False
    next_id: int = 1

    # ── ids ─────────────────────────────────────────────────────────────────
    def new_id(self, base: str) -> str:
        new = f"{base}-{self.next_id}"
        self.next_id += 1
        return new

    # ── characters ──────────────────────────────────────────────────────────
    def character(self, char_id: str) -> Character | None:
        return next((c for c in self.characters if c.id == char_id), None)

    def living(self) -> list[Character]:
        return [c for c in self.characters if c.status != "dead"]

    def active(self) -> list[Character]:
        return [c for c in self.characters if c.status == "ok"]

    # ── serialisation ───────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name == "characters":
                value = [c.to_dict() for c in value]
            elif f.name == "items":
                value = {k: v.to_dict() for k, v in value.items()}
            else:
                value = copy.deepcopy(value)
            out[f.name] = value
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GameState":
        data = copy.deepcopy(data)
        if data.get("version") != SAVE_VERSION:
            raise ValueError(f"Unsupported save version {data.get('version')}")
        data["characters"] = [Character.from_dict(c) for c in data.get("characters", [])]
        data["items"] = {k: Item.from_dict(v) for k, v in data.get("items", {}).items()}
        return cls(**data)

    def clone(self) -> "GameState":
        return GameState.from_dict(self.to_dict())


class SaveStore:
    """One save slot per adventure, written atomically."""

    def __init__(self, directory: Path = SAVES_DIR):
        self.directory = directory

    def path(self, adventure_id: str) -> Path:
        return self.directory / f"{adventure_id}.json"

    def exists(self, adventure_id: str) -> bool:
        return self.path(adventure_id).exists()

    def save(self, state: GameState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path(state.adventure_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def load(self, adventure_id: str) -> GameState:
        return GameState.from_dict(json.loads(self.path(adventure_id).read_text(encoding="utf-8")))

    def delete(self, adventure_id: str) -> None:
        self.path(adventure_id).unlink(missing_ok=True)
