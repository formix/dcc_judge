from dataclasses import dataclass, field

from marshmallow import Schema, fields, post_load, EXCLUDE


@dataclass
class Condition:
    """
    A status effect on a character.

    Attributes:
        name:        Label for the condition (e.g., "poisoned", "blind").
        rounds:      How many rounds remain. -1 means indefinite.
        target:      What is affected by it (e.g., "all rolls", "attack rolls", "sight", "ac").
        modifier:    Optional numeric modifier to apply while the condition is active (e.g., -2 to all rolls).
    """
    name: str
    rounds: int = -1     # -1 = indefinite
    target: str = ""     # e.g. "ac", "attack rolls", "all rolls"
    modifier: int = 0
    tags: set[str] = field(default_factory=set)


class ConditionSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name        = fields.Str(load_default="unknown")
    rounds      = fields.Int(load_default=-1)
    target      = fields.Str(load_default="")
    modifier    = fields.Int(load_default=0)
    tags        = fields.List(fields.Str(), load_default=list)

    @post_load
    def make(self, data, **kwargs) -> Condition:
        data["tags"] = set(data.get("tags") or [])
        return Condition(**data)
