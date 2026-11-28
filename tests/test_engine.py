import json

import pytest

from conftest import clear_hands, give, no_encounters, remove_groups, teleport
from engine import rules
from engine.adventure import Adventure, load_adventure
from engine.game import Game


def test_adventure_is_valid():
    errors, warnings = load_adventure("elders_secret").validate()
    assert errors == []


def test_validator_reports_broken_links():
    adv = Adventure({"id": "x", "start": "a", "scenes": [{"id": "a"}, {"id": "b"}],
                     "transitions": [{"id": "t", "from": "a", "to": "nowhere"}]})
    errors, _ = adv.validate()
    assert any("nowhere" in e for e in errors)


def test_new_game_party_and_save_round_trip(new_game, tmp_path):
    game = new_game(3)
    assert len(game.state.characters) == 4
    assert len({c.name for c in game.state.characters}) == 4
    for c in game.state.characters:
        assert 1 <= c.hp == c.max_hp
        assert c.augur["name"]
    loaded = Game.load("elders_secret", store=game.store, log_dir=None)
    assert loaded.state.to_dict() == game.state.to_dict()


def test_first_torch_lights_free_and_burns(new_game):
    game = new_game()
    no_encounters(game)
    clear_hands(game)
    give(game, 0, "Torch", 2)
    give(game, 0, "Flint & steel")
    start = game.state.clock
    result = game.command("sneak up goat path")
    assert result["ok"], result
    assert game.state.scene == "gate"
    assert game.state.clock == start + 10
    lit = [i for i in game.world().party_items() if i.state.get("lit")]
    assert len(lit) == 1 and lit[0].state["remaining"] == 50


def test_darkness_multiplies_time(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "slag")
    remove_groups(game, "slag")
    world = game.world()
    assert world.mode in ("infravision", "touch")
    leader = world.leader
    expected = 20 if leader.infravision else 40
    start = game.state.clock
    game.command("search")
    assert game.state.clock - start == expected


def test_torch_burns_out_into_darkness(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "slag")
    remove_groups(game, "slag")
    clear_hands(game)
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 5})
    result = game.command("wait")
    texts = " ".join(e["text"] for e in result["events"])
    assert "burns out" in texts and "Darkness" in texts
    assert torch.id not in game.state.items


def test_locked_door_and_key(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "forge")
    remove_groups(game, "forge")
    result = game.command("go banded door")
    assert not result["ok"] and "locked" in result["errors"][0]
    world = game.world()
    from engine.adventure import parse_item
    world.add_item(parse_item({"id": "skarn_key", "name": "key", "portable": True}),
                   {"char": game.state.characters[0].id, "slot": "pack"})
    result = game.command("go banded door")
    assert result["ok"], result
    assert game.state.scene == "pact"


def test_squeaky_door_is_loud_until_oiled(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "gate")
    remove_groups(game, "gate")
    game.state.encounter.update({"level": 1, "start": 1})
    game.level_service = lambda level, start, events: level + events.count("loud")  # record noise only
    game.command("go north door")
    assert game.state.encounter["level"] == 2
    # back, oil it, and go again quietly
    game2 = game
    game2.state.scene = "gate"
    world = game2.world()
    world.change("gate", "set_state", target="squeak_door", key="open", value=False)
    game2.command("take crock")
    assert game2.command("oil door")["ok"]
    game2.state.encounter["level"] = 1
    game2.command("go north door")
    assert game2.state.encounter["level"] == 1


def test_hidden_passage_found_by_searching_the_wall(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "cells")
    assert "cells_pact" not in [e["id"] for e in game.world().exits()]
    clear_hands(game)
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 60})
    game.command("search east wall")
    assert "cells_pact" in [e["id"] for e in game.world().exits()]


def test_trap_springs_unless_found(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "slag")
    remove_groups(game, "slag")
    clear_hands(game)
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 60})
    game.command("search footprints")
    assert "quench_plate" in game.state.discovered
    result = game.command("go causeway")
    assert "step over" in result["summary"] or "stride over" in result["summary"]
    assert torch.state["lit"]


def test_trap_douses_light(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "slag")
    remove_groups(game, "slag")
    clear_hands(game)
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 60})
    result = game.command("go causeway")
    assert "Steam" in result["summary"] or "steam" in result["summary"]
    assert not torch.state["lit"]


def test_combat_runs_to_an_end(new_game):
    game = new_game(11)
    no_encounters(game)
    clear_hands(game, 0)
    give(game, 0, "Torch", 2)
    give(game, 0, "Flint & steel")
    game.command("go goat path")          # noticed by the sentries
    assert game.state.phase == "combat"
    start = game.state.clock
    for _ in range(40):
        if game.state.phase != "combat":
            break
        game.command("all attack")
    assert game.state.phase in ("exploration", "over")
    if game.state.phase == "exploration":
        assert game.state.clock == start + 10
        assert all(c.status != "fallen" for c in game.state.characters)


def test_occupation_rule_dice(new_game):
    game = new_game()
    world = game.world()
    char = game.state.characters[0]
    game.state.scene = "outside"
    assert rules.check_die(world, char, True) == 20
    assert rules.check_die(world, char, False) == 10
    teleport(game, "slag")
    remove_groups(game, "slag")
    expected = (16, 8)
    assert (rules.check_die(world, char, True), rules.check_die(world, char, False)) == expected


def test_improvised_transform_makes_a_club(new_game):
    game = new_game()
    no_encounters(game)
    teleport(game, "cells")
    clear_hands(game)
    torch = give(game, 0, "Torch", slot="hands")
    torch.state.update({"lit": True, "remaining": 60})
    proposal = {"actions": [{"type": "improvise", "method": "smash chair", "loud": True, "ops": [{
        "op": "transform", "source": "jailer_chair",
        "description": {"light": "The chair lies in pieces.", "infravision": "Pieces of a chair.", "touch": "Splinters."},
        "creates": [{"name": "chair leg", "weapon": "light", "material": "wood"}]}]}]}
    result = game.act(json.dumps(proposal))
    assert result["ok"], result
    leg = next(i for i in game.state.items.values() if i.label() == "chair leg")
    assert leg.rules["weapon"]["damage"] == "1d3"
    chair = game.world().fixed_objects("cells")["jailer_chair"]
    assert chair.broken
    # a broken object cannot be broken again
    again = game.act(json.dumps(proposal))
    assert not again["ok"]


def test_judge_cannot_choose_damage_dice(new_game):
    game = new_game()
    teleport(game, "cells")
    proposal = {"actions": [{"type": "improvise", "ops": [{"op": "transform", "source": "jailer_chair",
                                                            "creates": [{"name": "stake", "weapon": "2d8"}]}]}]}
    result = game.act(proposal)
    assert not result["ok"]


def test_invalid_proposals_change_nothing(new_game):
    game = new_game()
    before = game.state.to_dict()
    result = game.act({"actions": [{"type": "teleport"}]})
    assert not result["ok"]
    assert game.state.to_dict() == before


def test_context_hides_undiscovered_things(new_game):
    game = new_game()
    teleport(game, "cells")
    text = json.dumps(game.context())
    assert "alda_tag" not in text and "cells_pact" not in text


def test_shop_buy_and_haggle(new_game):
    game = new_game()
    total = sum(c.cp for c in game.state.characters)
    assert game.command("buy 2 torches")["ok"]
    assert sum(c.cp for c in game.state.characters) == total - 2


def test_unknown_commands_go_to_the_judge(new_game):
    game = new_game()
    result = game.command("I whistle a sad tune for the goats")
    assert result["handled"] is False and "context" in result


def test_first_character_leads_and_leader_can_change(new_game):
    game = new_game()
    first, second = game.state.characters[0], game.state.characters[1]
    assert game.state.leader == first.id
    assert game.command("status")["leader"] == first.name
    for text in (f"leader {second.name}", f"{first.name} leads", f"make {second.name} leader",
                 f"set leader to {first.name}", f"{second.name} is the leader"):
        result = game.command(text.lower())
        assert result["handled"] and result["ok"], (text, result)
    assert game.state.leader == second.id
    assert game.command("look")["leader"] == second.name


def test_inventory_lists_equipment_slots_and_free_space(new_game):
    game = new_game()
    char = game.state.characters[0]
    clear_hands(game)
    give(game, 0, "Torch", 3)
    give(game, 0, "Shortbow", slot="hands")
    result = game.inventory(char.name)
    view = result["inventory"][0]
    assert result["display_only"] and view["name"] == char.name
    assert set(view["equipment"]) == {"hands", "body", "head"}
    assert len(view["equipment"]["hands"]) == 2 and view["free_hands"] == 0   # bow is two-handed
    torches = next(i for i in view["pack"] if i["name"] == "Torch")
    assert torches["quantity"] == 3 and torches["slots"] == 2               # two torches per slot
    assert view["slots"]["used"] + view["slots"]["free"] == view["slots"]["total"] == 10
    assert view["slots"]["used"] == sum(i["slots"] for i in view["pack"]) + view["coins"]["slots"]
    whole_party = game.inventory()["inventory"]
    assert len(whole_party) == 4
    # the parser path returns the same data on its event
    event = game.command(f"inventory {char.name.lower()}")["events"][0]
    assert event["kind"] == "inventory" and event["inventory"]["slots"] == view["slots"]
