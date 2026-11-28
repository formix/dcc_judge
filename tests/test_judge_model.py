"""
The Judge model interpreting free-form commands, checked by the engine.

Uses the Ollama model in DCC_JUDGE_TEST_MODEL (default gemma4-12b-128k:latest)
at DCC_JUDGE_TEST_HOST (default local). Skipped when Ollama or the model is not
available. These tests are slow: each command is a model call.
"""

import json
import os

import pytest

from conftest import clear_hands, give, no_encounters, remove_groups, teleport

MODEL = os.environ.get("DCC_JUDGE_TEST_MODEL", "gemma4-12b-128k:latest")
HOST = os.environ.get("DCC_JUDGE_TEST_HOST")


def _judge():
    try:
        import ollama
        client = ollama.Client(host=HOST) if HOST else ollama.Client()
        names = {m.model for m in client.list().models}
    except Exception as exc:  # Ollama not running
        pytest.skip(f"Ollama not available: {exc}")
    if MODEL not in names:
        pytest.skip(f"Model {MODEL} not pulled")
    from cli.judge import ModelJudge
    return ModelJudge(MODEL, HOST)


@pytest.fixture(scope="module")
def judge():
    return _judge()


def interpret(judge, game, text):
    """The Judge's turn: engine first, model only if the parser declines."""
    result = game.command(text)
    if result.get("handled", True):
        return None, result
    proposal = judge.interpret(text, result["context"])
    result = game.act(proposal)
    if not result["ok"] and not result["events"]:
        proposal = judge.interpret(text, result.get("context") or game.context(), result["errors"])
        result = game.act(proposal)
    return json.loads(proposal) if isinstance(proposal, str) else proposal, result


pytestmark = pytest.mark.model


def test_buying_light_in_plain_words(judge, new_game):
    game = new_game(5)
    proposal, result = interpret(judge, game, "I'd like three torches and some flint and steel to light them")
    assert result["ok"], result
    bought = [a for a in proposal["actions"] if a["type"] == "buy"]
    assert any("torch" in str(a["target"]).lower() for a in bought)
    assert any("flint" in str(a["target"]).lower() for a in bought)


def test_sneaking_in_plain_words(judge, new_game):
    game = new_game(5)
    no_encounters(game)
    proposal, result = interpret(judge, game, "We creep quietly up the path toward the smoke, keeping low")
    assert result["ok"], result
    move = next(a for a in proposal["actions"] if a["type"] == "move")
    assert move.get("silent") is True
    assert game.state.scene == "gate"


def test_improvised_club_from_a_chair(judge, new_game):
    game = new_game(5)
    no_encounters(game)
    teleport(game, "cells")
    clear_hands(game)
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 60})
    proposal, result = interpret(judge, game, "I smash the jailer's chair and take one of its legs as a club")
    kinds = [a["type"] for a in proposal["actions"]]
    assert "improvise" in kinds, proposal
    chair = game.world().fixed_objects("cells")["jailer_chair"]
    rolled = any(e["kind"] == "check" for e in result["events"])
    # Either it worked, or a fair check failed: both are valid rulings.
    assert chair.broken or rolled, result
    if chair.broken:
        leg = [i for i in game.state.items.values() if "weapon" in i.rules and i.rules["weapon"].get("improvised")]
        assert leg, "breaking the chair should make an improvised weapon"


def test_judge_does_not_invent_a_key(judge, new_game):
    game = new_game(5)
    no_encounters(game)
    teleport(game, "forge")
    remove_groups(game, "forge")
    before = set(game.state.items)
    interpret(judge, game, "I search the desk and find the key to the banded door")
    new_items = set(game.state.items) - before
    assert not any("key" in game.state.items[i].label().lower() for i in new_items)
    assert game.state.scene == "forge"
