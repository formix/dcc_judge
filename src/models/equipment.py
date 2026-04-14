from __future__ import annotations

from dataclasses import dataclass, field

from marshmallow import Schema, fields, post_load, EXCLUDE

from models.condition import Condition, ConditionSchema


@dataclass
class Equipment:
    """
    A single item in a character's inventory.

    Attributes:
        name:       Item name (e.g., "Torch", "Healing potion").
        quantity:   How many of this item are carried. Default 1.
        weight:     Item weight in pounds. Default 0.0 (negligible).
        charges:    Number of uses/charges remaining. -1 means unlimited/N/A.
        source:     Where the item came from (e.g., "starting equipment", "looted").
        conditions: Conditions this item grants while equipped/active.
        tags:       Category tags for the item (e.g., ["armor"], ["weapon"]) used for filtering or special interactions.
        modifier:   Numeric bonus/penalty this item contributes (e.g., +2 AC for a shield).
    """
    name: str
    quantity: int = 1
    weight: float = 0.0
    charges: int = -1          # -1 = not applicable
    source: str = "starting equipment"
    modifier: int = 0
    conditions: list[Condition] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)


class EquipmentSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name       = fields.Str(load_default="unknown")
    quantity   = fields.Int(load_default=1)
    weight     = fields.Float(load_default=0.0)
    charges    = fields.Int(load_default=-1)
    source     = fields.Str(load_default="starting equipment")
    modifier   = fields.Int(load_default=0)
    conditions = fields.List(fields.Nested(lambda: ConditionSchema()), load_default=list)

    @post_load
    def make(self, data, **kwargs) -> Equipment:
        data["tags"] = set(data.get("tags") or [])
        return Equipment(**data)
