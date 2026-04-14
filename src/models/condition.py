from dataclasses import dataclass, field

from marshmallow import Schema, fields, post_load, EXCLUDE


@dataclass
class Condition:
    """
    A temporary status effect on a character.

    Attributes:
        name:        Label for the condition (e.g., "poisoned", "blind").
        rounds:      How many rounds remain. -1 means indefinite.
        source:      What caused it (e.g., "Giant Spider bite").
        modifier:    Optional numeric modifier to apply while the condition is active (e.g., -2 to all rolls).
        tags:        Category tags for the condition (e.g., ["armor"], ["poison", "curse"]) used for filtering or special interactions.
    """
    name: str
    rounds: int          # -1 = indefinite
    source: str
    modifier: int = 0
    tags: set[str] = field(default_factory=set)


class ConditionSchema(Schema):
    class Meta:
        unknown = EXCLUDE

    name        = fields.Str(load_default="unknown")
    rounds      = fields.Int(load_default=-1)
    source      = fields.Str(load_default="")
    modifier    = fields.Int(load_default=0)
    tags        = fields.List(fields.Str(), load_default=list)

    @post_load
    def make(self, data, **kwargs) -> Condition:
        data["tags"] = set(data.get("tags") or [])
        return Condition(**data)
