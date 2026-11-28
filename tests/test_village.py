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


def test_the_shop_shows_each_characters_money(new_game):
    from engine.world import money_text
    assert money_text(1234) == "12 gp 3 sp 4 cp" and money_text(0) == "0 cp" and money_text(40) == "4 sp"
    game = new_game()
    assert "purse" not in game.command("look")                      # not in the tavern
    for char, cp in zip(game.state.characters, (39, 5, 0, 120)):
        char.cp = cp
    result = game.command("visit the shopkeeper")
    purse = result["purse"]
    assert [(c["name"], c["cp"]) for c in purse["characters"]] == [(c.name, c.cp) for c in game.state.characters]
    assert purse["party_cp"] == 164 and purse["characters"][0]["leader"]
    assert f"{game.state.characters[0].name} 3 sp 9 cp" in result["summary"]
    after = game.command("buy 3 torches")
    assert after["purse"]["characters"][0]["text"] == "3 sp 6 cp"


def test_shop_actions_use_the_named_character_or_the_leader(new_game):
    from engine.catalog import make_item
    game = new_game()
    game.command("visit the shopkeeper")
    leader, gilda, pim = game.state.characters[0], game.state.characters[1], game.state.characters[2]
    leader.cp, gilda.cp, pim.cp = 50, 3, 0
    world = game.world()
    # default: the leader buys and carries it
    assert game.command("buy 2 torches")["ok"]
    assert leader.cp == 48 and any(i.label() == "Torch" for i in world.char_items(leader.id))
    # named: that character buys; the others chip in when they run short
    result = game.command(f"{gilda.name.lower()} buy 5 torches")
    assert result["ok"] and gilda.cp == 0 and leader.cp == 46
    assert f"{gilda.name} buys 5 Torch for 5 cp ({leader.name} adds 2 cp)." in result["summary"]
    assert any(i.label() == "Torch" and i.quantity == 5 for i in world.char_items(gilda.id))
    # named seller and haggler: their own item, their own Personality, their purse
    world.add_item(make_item("Rope"), {"char": pim.id, "slot": "pack"})
    haggle = game.command(f"{pim.name.lower()} haggle rope")
    assert haggle["needs_confirmation"] and f"Haggling: {pim.name}" in haggle["summary"]
    sold = game.command("yes")
    assert sold["ok"] and pim.cp > 0 and not any(i.label() == "Rope" for i in world.char_items(pim.id))
    # the leader cannot sell what someone else carries
    world.add_item(make_item("Chalk"), {"char": pim.id, "slot": "pack"})
    refused = game.command("sell chalk")
    assert not refused["ok"] and f"{leader.name} does not have the Chalk; {pim.name} does." in refused["errors"][0]
