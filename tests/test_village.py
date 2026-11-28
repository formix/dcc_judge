"""Design 13: every game begins in the village tavern."""

from pathlib import Path

import pytest

from conftest import give
from engine.adventure import Adventure, AdventureError, load_adventure, with_village
from engine.game import Game
from engine.state import SaveStore
from rulesets.dcc import load_table


def test_game_begins_in_the_tavern_of_a_rolled_village(new_game):
    game = new_game(8)
    names = load_table("village_names")
    assert game.state.scene == "village_tavern"
    assert game.state.village["name"] in names["villages"]
    assert game.state.village["tavern"] in names["taverns"]
    context = game.context()
    assert context["scene"]["name"] == game.state.village["tavern"]
    assert game.state.village["name"] in context["scene"]["description"]
    assert [a["label"] for a in context["available_actions"]] == ["Glean rumors", "Visit the shopkeeper"]
    assert [e["id"] for e in context["scene"]["exits"]] == ["tavern_shop"]   # the road is hidden


def test_gleaning_reveals_the_hook_first_then_rumors(new_game):
    game = new_game()
    first = game.command("glean rumors")
    assert first["events"][-1]["kind"] == "hook"
    assert "Crane" in first["summary"] and game.state.village["name"] in first["summary"]
    assert "village_road" in [e["id"] for e in game.world().exits()]
    assert "Take the road to the forge under the hills" in [a["label"] for a in first["available_actions"]]
    second = game.command("listen for rumours")
    assert second["events"][-1]["kind"] == "rumor"
    for _ in range(10):
        last = game.command("glean rumors")
    assert "nothing you have not heard" in last["summary"]


def test_the_road_takes_three_hours_burns_no_torch_and_starts_the_deadline(new_game):
    game = new_game()
    game.command("glean rumors")
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 60})
    assert game.world().deadline_at() is None
    start = game.state.clock
    result = game.command("take the road")
    assert result["ok"], result
    assert game.state.scene == "outside"
    assert game.state.clock == start + 180
    assert torch.state["remaining"] == 60
    assert game.world().deadline_at() == start + 1440
    back = game.command("go road back to village")
    assert back["ok"] and game.state.scene == "village_tavern" and game.state.clock == start + 360


def test_level_0_party_needs_a_funnel(tmp_path):
    path = tmp_path / "adventure.yaml"
    text = (Path(__file__).resolve().parents[1] / "adventures" / "elders_secret" / "adventure.yaml").read_text()
    path.write_text(text.replace("number: F01", "number: A01").replace("funnel: true", "funnel: false"))
    with pytest.raises(AdventureError, match="not a funnel"):
        Game.new(str(path), store=SaveStore(tmp_path), log_dir=None)


def test_funnel_flag_must_match_the_f_number():
    base = {"id": "x", "scenes": [{"id": "gate"}], "transitions": [],
            "hook": {"text": "t", "destination": "d", "entrance": "gate"}}
    errors, _ = Adventure(with_village({**base, "number": "F02", "funnel": False})).validate()
    assert any("disagree" in e for e in errors)
    errors, _ = Adventure(with_village({**base, "number": "B01", "funnel": True})).validate()
    assert any("disagree" in e for e in errors)
    errors, _ = Adventure(with_village({**base, "number": "F02", "funnel": True})).validate()
    assert not any("disagree" in e for e in errors)


def test_every_adventure_needs_a_hook():
    with pytest.raises(AdventureError, match="hook"):
        with_village({"id": "x", "scenes": [], "transitions": []})
