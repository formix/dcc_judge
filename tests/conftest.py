import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from engine.catalog import make_item  # noqa: E402
from engine.game import Game  # noqa: E402
from engine.state import SaveStore  # noqa: E402


@pytest.fixture
def new_game(tmp_path):
    """Factory: a new Elder's Secret game with a fixed seed and a temporary save."""
    def make(seed: int = 1) -> Game:
        game, _ = Game.new("elders_secret", seed=seed, store=SaveStore(tmp_path), log_dir=None)
        return game
    return make


def give(game: Game, char_index: int, name: str, quantity: int = 1, slot: str = "pack"):
    world = game.world()
    char = game.state.characters[char_index]
    return world.add_item(make_item(name, quantity), {"char": char.id, "slot": slot})


def clear_hands(game: Game, char_index: int = 0) -> None:
    world = game.world()
    char = game.state.characters[char_index]
    for item in world.char_items(char.id, "hands"):
        world.move_item(item.id, {"char": char.id, "slot": "pack"})


def teleport(game: Game, scene: str) -> None:
    game.state.scene = scene
    if scene not in game.state.visited:
        game.state.visited.append(scene)
    game.world().ensure_scene_groups(scene)


def remove_groups(game: Game, scene: str) -> None:
    for group in game.state.groups.values():
        if group["scene"] == scene:
            for m in group["members"]:
                m["status"] = "dead"


def no_encounters(game: Game) -> None:
    game.state.encounter["level"] = 0
    game.state.encounter["start"] = 0
