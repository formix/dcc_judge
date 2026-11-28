from engine.dice import Dice, step_die
from engine.encounters import apply_level_events
from rulesets import dcc
from rulesets.game import RULES, result_table, table_lookup


def test_ability_modifiers_follow_table_1_1():
    expected = {3: -3, 4: -2, 5: -2, 6: -1, 7: -1, 8: 0, 12: 0, 13: 1, 15: 1, 16: 2, 17: 2, 18: 3}
    for score, mod in expected.items():
        assert dcc.get_ability_modifier(score) == mod
    assert dcc.get_ability_modifier(0) == -128


def test_tables_load_from_yaml():
    assert len(dcc.BIRTH_AUGURS) == 30
    assert dcc.BIRTH_AUGURS[22] == ("Charmed house", "ac")
    assert {a.name for a in dcc.ARMORS} >= {"Leather armor", "Shield"}
    shield = next(a for a in dcc.ARMORS if a.name == "Shield")
    assert shield.fumble == "d4"
    assert dcc.SAVE_ABILITIES["reflex"] == "Agility"
    assert dcc.INFRAVISION_RACES == {"Elf", "Dwarf", "Halfling"}
    assert dcc.ATTACK_MODIFIERS["missile_into_melee"] == (None, -1)


def test_range_tables_have_no_gaps():
    for name in ("crit_table_i", "fumble_table", "starting_equipment"):
        result_table(name)
    assert table_lookup("crit_table_i", -3)["effects"][1]["op"] == "disarm"
    assert table_lookup("fumble_table", 99)["min"] == 16


def test_dice_chain_steps():
    assert step_die(20, -1) == 16
    assert step_die(10, -1) == 8
    assert step_die(3, -5) == 3


def test_dice_are_seedable():
    assert [Dice(5).roll("3d6").total for _ in range(3)] == [Dice(5).roll("3d6").total for _ in range(3)]


def test_encounter_level_rules():
    assert apply_level_events(1, 1, ["loud"]) == 2
    assert apply_level_events(3, 1, ["loud"]) == 3          # capped
    assert apply_level_events(2, 1, ["silent", "silent"]) == 1  # floor is the start level
    assert apply_level_events(1, 1, ["dark_10", "dark_10"]) == 3
    assert apply_level_events(3, 1, ["quiet_light_10"]) == 2


def test_vision_table_matches_design():
    assert RULES["vision"]["infravision"]["time_multiplier"] == 2
    assert RULES["vision"]["touch"]["time_multiplier"] == 4
    assert RULES["surprise"] == {"light": 2, "infravision": 3, "touch": 5}
