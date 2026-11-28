"""
Item: the single model for scene objects and equipment (docs/design.md 4.2).

Basic parameters are id, name, description and material. Behaviour comes from
named rules in `rules`. Changeable state (broken, burning, lit, minutes left,
soaked, patched, open, locked, oiled...) lives in `state`.

A Text is either a plain string (used for every perception mode) or a dict with
"light", "infravision" and "touch" versions.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
from typing import Any

Text = str | dict[str, str]


def text_for(text: Text | None, mode: str) -> str | None:
    """Return the version of a Text for a perception mode, or None if absent.

    A plain string counts as the light version only, so that it is never shown
    to a party that cannot see it.
    """
    if text is None:
        return None
    if isinstance(text, str):
        return text if mode == "light" else None
    return text.get(mode)


@dataclass
class Item:
    id: str
    name: Text
    description: Text = ""
    material: str = "misc"
    rules: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    portable: bool = True
    quantity: int = 1
    cost_cp: int = 0
    state: dict[str, Any] = field(default_factory=dict)
    hidden: dict[str, Any] | None = None
    interactions: list[dict[str, Any]] = field(default_factory=list)

    # ── perception ──────────────────────────────────────────────────────────
    def label(self, mode: str = "light") -> str:
        """The name the party perceives, or a generic word if none."""
        name = text_for(self.name, mode)
        if name:
            return name
        return "something" if mode == "touch" else "a shape"

    def describe(self, mode: str = "light") -> str | None:
        override = self.state.get("description")
        if override is not None:
            text = text_for(override, mode)
            if text:
                return text
        return text_for(self.description, mode)

    # ── state helpers ───────────────────────────────────────────────────────
    @property
    def broken(self) -> bool:
        return self.state.get("integrity") == "broken"

    @property
    def burning(self) -> bool:
        return self.state.get("fire") == "burning"

    @property
    def gives_light(self) -> bool:
        if self.burning:
            return True
        return "light" in self.rules and bool(self.state.get("lit"))

    def has_rule(self, name: str) -> bool:
        return name in self.rules

    # ── serialisation ───────────────────────────────────────────────────────
    def to_dict(self) -> dict[str, Any]:
        return {f.name: copy.deepcopy(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Item":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ValueError(f"Unknown item fields {sorted(unknown)} in {data.get('id')}")
        return cls(**copy.deepcopy(data))

    def copy(self, **changes: Any) -> "Item":
        data = self.to_dict()
        data.update(changes)
        return Item.from_dict(data)
