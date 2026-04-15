from dataclasses import dataclass


@dataclass
class DiceRollResult:
    """Result of a single roll_dice call."""
    expression: str
    sides: int
    count: int
    modifier: int
    rolls: list[int]
    subtotal: int   # sum of dice before modifier
    total: int      # subtotal + modifier


@dataclass
class DiceChainResult:
    """Result of a roll_dice_chain call."""
    requested_die: int
    actual_die: int
    steps: int
    clamped: bool
    roll: int
