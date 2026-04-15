from __future__ import annotations

from dataclasses import dataclass, field

from marshmallow import Schema, fields, post_load, pre_load, EXCLUDE

from rulesets.dcc import CHARACTER_ABILITIES, ABILITY_MODIFIERS, SLOTS
from models.condition import Condition, ConditionSchema
from models.equipment import Equipment, EquipmentSchema


@dataclass
class CharacterSheet:
    id: str = ""
    name: str = "Unknown Adventurer"
    occupation: str = "Peasant"
    race: str = "Human"           # must be in CHARACTER_RACES
    gender: str = "Male"          # must be in GENDERS
    alignment: str = "Neutral"    # must be in ALIGNEMENTS
    calling: str | None = None    # None = 0-level; non-humans use race as class
    level: int = 0
    abilities: dict[str, int] = field(
        default_factory=lambda: {a: 10 for a in CHARACTER_ABILITIES}
    )
    hp: int = 4
    equipment: list[Equipment] = field(default_factory=list)
    conditions: list[Condition] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    slots: dict[str, Equipment | None] = field(
        default_factory=lambda: {s: None for s in SLOTS}
    )

    def get_ac(self) -> int:
        """Compute AC = 10 + Agility modifier + sum of armor modifiers.

        Armor bonus comes from:
        - Conditions with target='ac' on items currently worn in slots.
        - Conditions with target='ac' applied directly to the character.
        """
        agility_mod = ABILITY_MODIFIERS.get(self.abilities.get("Agility", 10), 0)
        armor_mod = sum(
            c.modifier
            for eq in self.slots.values() if eq is not None
            for c in eq.conditions if c.target == "ac"
        ) + sum(
            c.modifier
            for c in self.conditions
            if c.target == "ac"
        )
        return 10 + agility_mod + armor_mod

    def equip(self, item_name: str, slot: str) -> Equipment:
        """
        Move an item from the equipment list into a slot.

        Rules:
        - Item must have tags ``wearable`` and the slot name (or ``ring`` for
          ring_left / ring_right).
        - ``two-handed`` items require both ``weapon`` and ``shield`` slots
          to be empty; equipping them fills only ``weapon`` (shield stays
          blocked by convention — callers may enforce the shield restriction).
        - Each slot holds at most one item; the previous occupant is returned
          to the equipment list.

        Raises:
            KeyError:   item_name not found in equipment list.
            ValueError: invalid slot, missing wearable/slot tags, or
                        two-handed conflict.
        """
        if slot not in SLOTS:
            raise ValueError(f"Unknown slot '{slot}'. Valid slots: {', '.join(SLOTS)}")

        # Find the item in the unequipped list — exact match first, then substring.
        needle = item_name.lower()
        item = next((e for e in self.equipment if e.name.lower() == needle), None)
        if item is None:
            item = next((e for e in self.equipment if needle in e.name.lower()), None)
        if item is None:
            available = ", ".join(f"'{e.name}'" for e in self.equipment) or "none"
            raise KeyError(
                f"No item matching '{item_name}' in equipment list. "
                f"Available: {available}."
            )

        if "wearable" not in item.tags:
            raise ValueError(f"'{item.name}' is not wearable (missing 'wearable' tag).")

        # Determine the required tag for the target slot.
        required_tag = "ring" if slot in ("ring_left", "ring_right") else slot
        if required_tag not in item.tags:
            raise ValueError(
                f"'{item.name}' cannot go in the '{slot}' slot "
                f"(missing '{required_tag}' tag)."
            )

        # Two-handed check.
        if "two-handed" in item.tags:
            if self.slots.get("weapon") is not None or self.slots.get("shield") is not None:
                raise ValueError(
                    "Two-handed weapon requires both 'weapon' and 'shield' slots to be empty."
                )

        # Return the current occupant to inventory.
        if self.slots[slot] is not None:
            self.equipment.append(self.slots[slot])  # type: ignore[arg-type]

        self.equipment.remove(item)
        self.slots[slot] = item
        return item

    def unequip(self, slot: str) -> Equipment:
        """
        Remove the item from *slot* and return it to the equipment list.

        Raises:
            KeyError:   slot name is not valid.
            ValueError: slot is already empty.
        """
        if slot not in SLOTS:
            raise ValueError(f"Unknown slot '{slot}'. Valid slots: {', '.join(SLOTS)}")
        item = self.slots[slot]
        if item is None:
            raise ValueError(f"Slot '{slot}' is already empty.")
        self.slots[slot] = None
        self.equipment.append(item)
        return item


class CharacterSheetSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    id         = fields.Str(load_default="")
    name       = fields.Str(load_default="Unknown Adventurer")
    occupation = fields.Str(load_default="Peasant")
    race       = fields.Str(load_default="Human")
    gender     = fields.Str(load_default="Male")
    alignment  = fields.Str(load_default="Neutral")
    calling    = fields.Str(load_default=None, allow_none=True)
    level      = fields.Int(load_default=0)
    abilities  = fields.Dict(keys=fields.Str(), values=fields.Int(), load_default=None)
    hp         = fields.Int(load_default=4)
    equipment  = fields.List(fields.Nested(EquipmentSchema), load_default=list)
    conditions = fields.List(fields.Nested(ConditionSchema), load_default=list)
    notes      = fields.List(fields.Str(), load_default=list)
    slots      = fields.Dict(
        keys=fields.Str(),
        values=fields.Nested(EquipmentSchema, allow_none=True),
        load_default=dict,
    )

    @pre_load
    def derive_calling(self, data, **kwargs) -> dict:
        race = data.get("race", "Human")
        if not data.get("calling"):
            data["calling"] = race if race != "Human" else None
        return data

    @post_load
    def make(self, data, **kwargs) -> CharacterSheet:
        if data["abilities"] is None:
            data["abilities"] = {a: 10 for a in CHARACTER_ABILITIES}
        # Ensure all slots are present even when loading old data.
        base_slots: dict[str, Equipment | None] = {s: None for s in SLOTS}
        base_slots.update(data.get("slots") or {})
        data["slots"] = base_slots
        return CharacterSheet(**data)
