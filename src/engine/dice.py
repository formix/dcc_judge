"""Seedable dice for the engine. Expressions use services.dice_service syntax."""

from __future__ import annotations

import random
from dataclasses import dataclass

from rulesets.dcc import DICE_CHAIN
from services.dice_service import _parse_expression


@dataclass
class Roll:
    expression: str
    rolls: list[int]
    modifier: int
    total: int

    def __str__(self) -> str:
        mod = f"{self.modifier:+d}" if self.modifier else ""
        return f"{self.expression}: {self.rolls}{mod} = {self.total}"


class Dice:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)

    def die(self, sides: int) -> int:
        return self.rng.randint(1, sides)

    def roll(self, expression: str | int) -> Roll:
        """Roll 'NdS+M', 'dS' or a fixed integer."""
        text = str(expression).strip()
        if text.lstrip("+-").isdigit():
            value = int(text)
            return Roll(text, [value], 0, value)
        count, sides, modifier = _parse_expression(text)
        rolls = [self.die(sides) for _ in range(count)]
        return Roll(text, rolls, modifier, sum(rolls) + modifier)

    def chance(self, probability: float) -> bool:
        return self.rng.random() < probability

    def choice(self, seq):
        return self.rng.choice(seq)

    def weighted(self, entries: list, weights: list[float]):
        return self.rng.choices(entries, weights=weights, k=1)[0]


def step_die(sides: int, steps: int) -> int:
    """Move a die along the DCC dice chain, clamped at its ends."""
    if steps == 0:
        return sides
    if sides not in DICE_CHAIN:
        raise ValueError(f"d{sides} is not on the dice chain")
    index = max(0, min(len(DICE_CHAIN) - 1, DICE_CHAIN.index(sides) + steps))
    return DICE_CHAIN[index]


def die_sides(expression: str) -> int:
    """Return S for 'dS' or '1dS'."""
    return _parse_expression(expression)[1]
