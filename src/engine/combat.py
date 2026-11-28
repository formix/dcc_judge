"""
Combat (docs/design.md 9; DCC combat rules; 2d6 morale).

state.combat holds the fight in progress:
    groups          creature group instance ids
    round           rounds resolved so far
    party_init      party initiative
    group_init      initiative per group
    orders          standing orders per character: {"type": "attack", "target": member_id} or {"type": "defend"}
    conditions      temporary combat conditions per character or creature id
    enemies_surprised  the party gets a free first round
"""

from __future__ import annotations

from typing import Any

from engine import rules
from engine.character import Character
from engine.dice import die_sides, step_die
from rulesets.dcc import (
    INITIATIVE_DIE,
    MINIMUM_DAMAGE,
    MISSILE_INTO_MELEE_FRIENDLY_FIRE,
    RECOVER_BODY_ABILITY_LOSS,
    RECOVER_BODY_GROGGY_MINUTES,
    RECOVER_BODY_GROGGY_PENALTY,
    TWO_HANDED_INITIATIVE_DIE,
    UNTRAINED_PENALTY_WAIVED_AT_LEVEL_0,
    UNTRAINED_WEAPON_DIE_STEPS,
    ZERO_LEVEL_CRIT_DIE,
    ZERO_LEVEL_CRIT_TABLE,
    ATTACK_MODIFIERS,
)
from rulesets.game import RULES, table_lookup


# ── helpers ─────────────────────────────────────────────────────────────────
def _combat(world) -> dict[str, Any]:
    return world.state.combat


def enemies(world) -> list[tuple[dict, dict]]:
    """(group, member) pairs still fighting."""
    out = []
    for gid in _combat(world)["groups"]:
        group = world.state.groups[gid]
        out += [(group, m) for m in group["members"] if m["status"] == "ok"]
    return out


def find_enemy(world, member_id: str) -> tuple[dict, dict] | None:
    return next(((g, m) for g, m in enemies(world) if m["id"] == member_id), None)


def front_limit(world) -> int:
    return world.scene.get("front_rank", 2)


def _conds(world, who: str) -> list[dict]:
    return _combat(world)["conditions"].setdefault(who, [])


def _add_cond(world, who: str, **cond: Any) -> None:
    _conds(world, who).append(cond)


def _cond_sum(world, who: str, name: str, consume: bool = False) -> int:
    total = 0
    for cond in list(_conds(world, who)):
        if cond["name"] == name:
            total += cond.get("value", 0)
            if consume and "attacks" in cond:
                cond["attacks"] -= 1
                if cond["attacks"] <= 0:
                    _conds(world, who).remove(cond)
    return total


def _has_cond(world, who: str, name: str) -> bool:
    return any(c["name"] == name for c in _conds(world, who))


def _member_name(world, member: dict) -> str:
    """'Nib the goblin sentry' for named creatures, so narrators read names as names."""
    if world.mode == "touch":
        return "something"
    kind = world.creature(member).get("name", member["creature"])
    name = member["name"]
    return name if name.lower().startswith(kind.lower()) or name == kind else f"{name} the {kind}"


# ── start ───────────────────────────────────────────────────────────────────
def start(world, group_ids: list[str], party_surprised: bool = False, enemies_surprised: bool = False) -> None:
    for gid in group_ids:
        world.state.groups[gid]["attitude"] = "hostile"
    leader = world.leader
    weapon = world.weapon_of(leader)
    die = TWO_HANDED_INITIATIVE_DIE if weapon and weapon.rules["weapon"].get("two_handed") else INITIATIVE_DIE
    party_init = world.dice.die(die) + leader.mod("Agility") + leader.augur_bonus("initiative")
    group_init = {}
    for gid in group_ids:
        spec = world.adventure.groups[world.state.groups[gid]["group"]]
        group_init[gid] = world.dice.die(INITIATIVE_DIE) + spec.get("initiative", 0)
    world.state.phase = "combat"
    world.state.combat = {
        "groups": list(group_ids), "round": 0, "party_init": party_init, "group_init": group_init,
        "orders": {}, "conditions": {}, "enemies_surprised": enemies_surprised,
        "start_clock": world.now,
    }
    names = ", ".join(_member_name(world, m) for _, m in enemies(world))
    world.emit("combat", f"Combat! Facing: {names}. (Party initiative {party_init}.)")
    if party_surprised:
        world.emit("surprise", "The party is caught by surprise.")
        for gid in _initiative_order(world):
            if gid != "party":
                _group_turn(world, world.state.groups[gid])
        _end_round_conditions(world)
        _check_end(world)


def _initiative_order(world) -> list[str]:
    combat = _combat(world)
    order = [("party", combat["party_init"], 1)] + [(gid, v, 0) for gid, v in combat["group_init"].items()]
    order.sort(key=lambda x: (x[1], x[2]), reverse=True)  # party wins ties (assumption)
    return [x[0] for x in order]


# ── a round ─────────────────────────────────────────────────────────────────
def set_order(world, char: Character, order: dict[str, Any]) -> None:
    _combat(world)["orders"][char.id] = order


def resolve_round(world) -> None:
    combat = _combat(world)
    combat["round"] += 1
    skip_groups = combat["round"] == 1 and combat.get("enemies_surprised")
    if skip_groups:
        world.emit("surprise", "The enemy is caught unaware.")
    for actor in _initiative_order(world):
        if world.state.phase != "combat":
            return
        if actor == "party":
            _party_turn(world)
        elif not skip_groups:
            _group_turn(world, world.state.groups[actor])
        if _check_end(world):
            return
    _end_round_conditions(world)


def _end_round_conditions(world) -> None:
    for who, conds in _combat(world)["conditions"].items():
        for cond in list(conds):
            if "rounds" in cond:
                cond["rounds"] -= 1
                if cond["rounds"] <= 0:
                    conds.remove(cond)


def _party_turn(world) -> None:
    for char in list(world.state.active()):
        if world.state.phase != "combat":
            return
        if _has_cond(world, char.id, "lose_actions") or _has_cond(world, char.id, "immobilised"):
            world.emit("combat", f"{char.name} cannot act this round.")
            continue
        order = _combat(world)["orders"].get(char.id, {"type": "defend"})
        if order["type"] != "attack":
            continue
        target = find_enemy(world, order.get("target", ""))
        if target is None:
            remaining = enemies(world)
            if not remaining:
                return
            target = remaining[0]
            order["target"] = target[1]["id"]
        if not can_reach(world, char):
            world.emit("combat", f"{char.name} cannot reach anyone from the rear rank.")
            continue
        character_attack(world, char, *target)


def can_reach(world, char: Character) -> bool:
    if char.id in {c.id for c in front_rank(world)}:
        return True
    weapon = world.weapon_of(char)
    rule = weapon.rules["weapon"] if weapon and not weapon.broken else {}
    return bool(rule.get("ranged") or rule.get("reach"))


def front_rank(world) -> list[Character]:
    """Who stands in front. Rear-rank characters step into gaps (assumption)."""
    active = world.state.active()
    limit = front_limit(world)
    front = [c for c in active if c.rank == "front"][:limit]
    front += [c for c in active if c not in front][: limit - len(front)]
    return front


def _group_turn(world, group: dict) -> None:
    for member in [m for m in group["members"] if m["status"] == "ok"]:
        if world.state.phase != "combat":
            return
        if _has_cond(world, member["id"], "lose_actions"):
            continue
        targets = front_rank(world)
        if not targets:
            return
        creature_attack(world, group, member, world.dice.choice(targets))


# ── attacks ─────────────────────────────────────────────────────────────────
def _apply_die_mod(die: int, mod) -> tuple[int, int]:
    if isinstance(mod, str):
        return step_die(die, int(mod.replace("d", ""))), 0
    return die, mod or 0


def character_attack(world, char: Character, group: dict, member: dict, ally_target: Character | None = None) -> None:
    creature = world.creature(member)
    weapon = world.weapon_of(char)
    if weapon is not None and weapon.broken:
        weapon = None
    wrule = weapon.rules["weapon"] if weapon else {}
    missile = bool(wrule.get("ranged") and (not wrule.get("melee") or char.rank == "rear"))
    mode = world.mode_for(char)
    vision = RULES["vision"][mode]
    die = step_die(20, vision["die_steps"])
    trained = weapon is not None and weapon.label().lower() == char.trained_weapon.lower()
    if weapon is not None and not trained and not (char.level == 0 and UNTRAINED_PENALTY_WAIVED_AT_LEVEL_0):
        die = step_die(die, UNTRAINED_WEAPON_DIE_STEPS)
    mod = char.mod("Agility" if missile else "Strength") + wrule.get("attack", 0)
    mod += char.augur_bonus("attack", "missile_attack" if missile else "melee_attack")
    if weapon is None:
        mod += char.augur_bonus("unarmed_attack")
    if trained:
        mod += char.augur_bonus("starting_weapon")
    mod += char.condition_modifier("attack", world.now) + _cond_sum(world, char.id, "attack_modifier", consume=True)
    if missile:
        die, extra = _apply_die_mod(die, ATTACK_MODIFIERS["missile_into_melee"][1])
        mod += extra
    if _has_cond(world, member["id"], "prone"):
        die, extra = _apply_die_mod(die, ATTACK_MODIFIERS["defender_prone"][1 if missile else 0])
        mod += extra
    roll = world.dice.die(die)
    name = _member_name(world, member)
    weapon_name = weapon.label() if weapon else "bare hands"
    if roll == 1:
        world.emit("attack", f"{char.name} fumbles with {weapon_name}!")
        fumble(world, char, weapon)
        return
    if world.dice.chance(vision["swing_at_nothing"]):
        world.emit("attack", f"{char.name} swings at nothing in the dark.")
        return
    crit = die == 20 and roll == 20
    total = roll + mod
    if not crit and total < creature["ac"]:
        world.emit("attack", f"{char.name} attacks {name} with {weapon_name} and misses (d{die} {roll}{mod:+d} = {total}).")
        allies = [c for c in front_rank(world) if c.id != char.id]
        if missile and allies and world.dice.chance(MISSILE_INTO_MELEE_FRIENDLY_FIRE):
            ally = world.dice.choice(allies)
            dmg = _damage_roll(world, char, weapon, wrule, missile, crit=False, creature=None)
            world.emit("attack", f"The shot strikes {ally.name} instead!")
            world.hurt(ally, dmg, "a stray shot")
        return
    dmg = _damage_roll(world, char, weapon, wrule, missile, crit, creature)
    text = f"{char.name} {'CRITICALLY ' if crit else ''}hits {name} with {weapon_name} (d{die} {roll}{mod:+d} = {total})"
    if crit:
        luck = char.mod("Luck") * (2 if char.augur.get("applies_to") == "crits" else 1)
        entry = table_lookup(ZERO_LEVEL_CRIT_TABLE, world.dice.die(ZERO_LEVEL_CRIT_DIE) + luck)
        world.emit("crit", entry["text"])
        dmg += _apply_table_effects(world, entry["effects"], char, member, weapon)
    dmg = max(MINIMUM_DAMAGE, dmg)
    world.emit("attack", f"{text} for {dmg} damage.")
    _hurt_member(world, group, member, dmg)


def _damage_roll(world, char, weapon, wrule, missile: bool, crit: bool, creature: dict | None) -> int:
    dice = wrule.get("damage") or RULES["unarmed_damage"]
    dmg = world.dice.roll(dice).total
    if not missile:
        dmg += char.mod("Strength")
    dmg += char.augur_bonus("damage", "missile_damage" if missile else "melee_damage")
    if weapon is not None and weapon.label().lower() == char.trained_weapon.lower():
        dmg += char.augur_bonus("starting_weapon")
    bane = (weapon.rules.get("bane") if weapon else None) or {}
    if creature and bane and set(bane.get("against", [])) & set(creature.get("kinds", [])):
        dmg += world.dice.roll(bane["damage"]).total
    return dmg


def creature_attack(world, group: dict, member: dict, char: Character) -> None:
    creature = world.creature(member)
    die = 20
    if not creature.get("sees_in_dark", True) and not world.party_has_light():
        die = step_die(20, -1)
    roll = world.dice.die(die)
    mod = creature.get("attack", 0) + _cond_sum(world, member["id"], "attack_modifier", consume=True)
    mod += _cond_sum(world, char.id, "defence_opening", consume=True)
    if _has_cond(world, char.id, "prone"):
        mod += ATTACK_MODIFIERS["defender_prone"][0]
    name = _member_name(world, member)
    ac = world.ac(char) + _cond_sum(world, char.id, "ac_modifier")
    if roll == 1:
        world.emit("attack", f"{name.capitalize()} lunges at {char.name} and misses badly.")
        return
    total = roll + mod
    crit = roll == 20
    if not crit and total < ac:
        world.emit("attack", f"{name.capitalize()} attacks {char.name} and misses.")
        return
    dmg = world.dice.roll(creature.get("damage", "1d4")).total
    if crit:
        for _ in range(RULES["monster_crit_damage_multiplier"] - 1):
            dmg += world.dice.roll(creature.get("damage", "1d4")).total
    dmg = max(MINIMUM_DAMAGE, dmg)
    world.emit("attack", f"{name.capitalize()} {'critically ' if crit else ''}hits {char.name} for {dmg} damage.")
    world.hurt(char, dmg, announce=False)


def _hurt_member(world, group: dict, member: dict, dmg: int) -> None:
    before = member["hp"]
    member["hp"] -= dmg
    triggers = []
    lone = len(group["members"]) == 1
    if lone and "first_hit" not in group["fired"]:
        triggers.append("first_hit")
    if lone and before > member["max_hp"] / 2 >= member["hp"] > 0:
        triggers.append("half_hp")
    if member["hp"] <= 0:
        member["status"] = "dead"
        world.emit("kill", f"{_member_name(world, member).capitalize()} is slain.")
        dead = [m for m in group["members"] if m["status"] == "dead"]
        if len(dead) == 1:
            triggers.append("first_death")
        if len(dead) >= len(group["members"]) / 2:
            triggers.append("half_dead")
        if member.get("chief"):
            triggers.append("chief_death")
    morale(world, group, triggers)


# ── critical hits and fumbles ───────────────────────────────────────────────
def fumble(world, char: Character, weapon) -> None:
    luck = char.mod("Luck") * (2 if char.augur.get("applies_to") == "fumbles" else 1)
    die = die_sides(world.fumble_die(char))
    entry = table_lookup("fumble_table", world.dice.die(die) - luck)
    world.emit("fumble", entry["text"])
    _apply_table_effects(world, entry["effects"], char, None, weapon)


def _who(world, spec: str, char: Character, member: dict | None):
    return member if spec == "target" else char


def _apply_table_effects(world, effects: list[dict], char: Character, member: dict | None, weapon) -> int:
    """Apply critical or fumble effects; returns extra damage for the strike."""
    extra = 0
    for e in effects:
        op = e["op"]
        who = _who(world, e.get("who", "actor"), char, member)
        who_id = who["id"] if isinstance(who, dict) else who.id
        if op == "extra_damage":
            extra += world.dice.roll(e["dice"]).total
        elif op == "damage":
            _damage_any(world, who, world.dice.roll(e["dice"]).total, member)
        elif op == "weapon_damage":
            wrule = weapon.rules["weapon"] if weapon else {}
            dmg = world.dice.roll(wrule.get("damage") or RULES["unarmed_damage"]).total + e.get("bonus", 0)
            _damage_any(world, who, max(1, dmg), member)
        elif op == "disarm":
            if isinstance(who, dict):
                _add_cond(world, who_id, name="lose_actions", rounds=1)
                world.emit("crit", f"{_member_name(world, who).capitalize()} loses its weapon and a moment recovering it.")
            elif weapon is not None:
                world.move_item(weapon.id, {"scene": world.state.scene})
                world.emit("fumble", f"{char.name}'s {weapon.label()} lands on the floor.")
        elif op == "disable_weapon" and weapon is not None:
            weapon.state["integrity"] = "broken"
            world.emit("fumble", f"{char.name}'s {weapon.label()} is useless until repaired.")
        elif op == "destroy_weapon" and weapon is not None and not weapon.rules.get("magic"):
            world.remove_item(weapon.id)
            world.emit("fumble", f"{char.name}'s {weapon.label()} is ruined.")
        elif op == "condition":
            if e.get("only_if") == "armoured" and isinstance(who, Character) and world.fumble_die(who) == "d4":
                continue
            rounds = e.get("rounds", 1)
            rounds = world.dice.roll(rounds).total if isinstance(rounds, str) else rounds
            _add_cond(world, who_id, name=e["name"], rounds=rounds)
        elif op == "save":
            if isinstance(who, Character):
                ok = rules.saving_throw(world, who, e["save"], e["dc"])["success"]
            else:
                ok = world.dice.die(20) + world.creature(who).get("saves", 0) >= e["dc"]
            if not ok:
                extra += _apply_table_effects(world, e["on_failure"], char, member, weapon)
        elif op == "attack_modifier":
            _add_cond(world, who_id, name="attack_modifier", value=e["value"], attacks=e.get("attacks", 1))
        elif op == "ac_modifier":
            _add_cond(world, who_id, name="ac_modifier", value=e["value"])
        elif op == "defence_opening":
            _add_cond(world, who_id, name="defence_opening", value=e["enemy_bonus"], attacks=e.get("attacks", 1))
        elif op == "lose_actions":
            _add_cond(world, who_id, name="lose_actions", rounds=e.get("rounds", 1))
        elif op == "initiative_last":
            _add_cond(world, who_id, name="lose_actions", rounds=1)
        elif op in ("speed_penalty", "free_attack"):
            pass  # no effect with front and rear ranks (design 11.2)
        elif op == "attack_ally":
            allies = [c for c in world.state.active() if c.id != char.id]
            if allies:
                ally = world.dice.choice(allies)
                wrule = weapon.rules["weapon"] if weapon else {}
                if world.dice.die(20) + char.mod("Strength") >= world.ac(ally):
                    dmg = max(1, world.dice.roll(wrule.get("damage") or RULES["unarmed_damage"]).total)
                    world.emit("fumble", f"{char.name}'s blow lands on {ally.name}!")
                    world.hurt(ally, dmg)
                else:
                    world.emit("fumble", f"{char.name} narrowly misses {ally.name}.")
        else:
            raise ValueError(f"Unknown table effect '{op}'")
    return extra


def _damage_any(world, who, amount: int, member: dict | None) -> None:
    if isinstance(who, Character):
        world.hurt(who, amount)
    else:
        group = next(g for g, m in enemies(world) if m["id"] == who["id"])
        _hurt_member(world, group, who, amount)


# ── morale (old-school 2d6) ─────────────────────────────────────────────────
def morale(world, group: dict, triggers: list[str]) -> None:
    new = [t for t in triggers if t not in group["fired"]]
    if not new or group["fearless"]:
        group["fired"] += new
        return
    group["fired"] += new
    alive = [m for m in group["members"] if m["status"] == "ok"]
    if not alive:
        return
    spec = world.adventure.groups[group["group"]]
    rank_and_file = [m for m in alive if not m.get("chief")] or alive
    score = spec.get("morale", world.creature(rank_and_file[0]).get("morale"))
    if score is None:
        return  # never checks morale
    if any(m.get("chief") for m in alive) and len(alive) > 1:
        score = min(RULES["morale"]["max_score"], score + RULES["morale"]["chief_bonus"])
    roll = world.dice.roll(RULES["morale"]["dice"]).total
    if roll <= score:
        group["morale_successes"] += 1
        if group["morale_successes"] >= RULES["morale"]["fearless_after_successes"]:
            group["fearless"] = True
        world.emit("morale", f"The enemy holds its ground (morale {roll} vs {score}).")
        return
    outcome = spec.get("morale_fail") or world.creature(rank_and_file[0]).get("morale_fail", "flee")
    for m in alive:
        m["status"] = "surrendered" if outcome == "surrender" else "fled"
    verb = "throws down its weapons and surrenders" if outcome == "surrender" else "breaks and flees"
    world.emit("morale", f"The enemy {verb} (morale {roll} vs {score}).")
    if outcome != "surrender":
        group["scene"] = spec.get("flees_to", "")
        if spec.get("on_flee"):
            world.run_effects(spec["on_flee"], None)


# ── ending a fight ──────────────────────────────────────────────────────────
def _check_end(world) -> bool:
    if world.state.phase != "combat":
        return True
    if not world.state.active():
        defeat(world)
        return True
    if not enemies(world):
        victory(world)
        return True
    return False


def defeat(world) -> None:
    for char in world.state.characters:
        if char.status == "fallen":
            world.kill(char, "No one is left to turn the body over.")
    world.state.combat = None
    world.state.phase = "over"
    world.state.outcome = "lost"
    world.emit("defeat", "The whole party has fallen. The adventure ends here.")


def _finish(world) -> None:
    # Design 4.7: a quick repair lasts one combat, then the item is unusable forever.
    for item in world.party_items():
        if item.state.get("patched") and world.location(item.id).get("slot") in ("hands", "worn"):
            item.state.update({"patched": False, "integrity": "broken", "unusable": True})
            world.emit("repair", f"The patched {item.label()} gives way for good.")
    world.state.combat = None
    world.state.phase = "exploration"
    world.advance(RULES["combat_minutes"])


def victory(world) -> None:
    world.emit("victory", "The fight is over.")
    for group_id in _combat(world)["groups"]:
        group = world.state.groups[group_id]
        for member in group["members"]:
            if member["status"] == "dead" and not member.get("looted"):
                member["looted"] = True
                for loot in world.creature(member).get("loot", []):
                    from engine.adventure import parse_item
                    item = parse_item(loot if isinstance(loot, dict) else {"catalog": loot, "portable": True})
                    world.add_item(item, {"scene": world.state.scene})
                    world.emit("loot", f"On the body of {member['name']}: {item.label()}.")
    for char in world.state.characters:
        if char.status == "fallen":
            recover_body(world, char)
    _finish(world)


def recover_body(world, char: Character) -> None:
    """DCC 'recovering the body': a Luck check when the body is rolled over."""
    result = rules.luck_check(world, char)
    world.emit("check", result["text"])
    if not result["success"]:
        world.kill(char, "There is no life left in the body.")
        return
    char.status = "ok"
    char.hp = 1
    char.fallen_at = None
    lost = world.dice.choice(list(RECOVER_BODY_ABILITY_LOSS))
    char.abilities[lost] -= 1
    char.conditions.append({"name": "groggy", "target": "all rolls", "modifier": RECOVER_BODY_GROGGY_PENALTY,
                            "until": world.now + RULES["combat_minutes"] + RECOVER_BODY_GROGGY_MINUTES})
    world.emit("recover", f"{char.name} gasps back to life with 1 HP, groggy, and permanently weaker ({lost} -1).")


def flee(world, exit_info: dict) -> None:
    """Everyone standing leaves together; each engaged enemy gets one parting attack."""
    world.emit("flee", "The party flees!")
    for group, member in enemies(world):
        targets = front_rank(world)
        if not targets:
            break
        if world.creature(member).get("no_parting_attack"):
            continue
        creature_attack(world, group, member, world.dice.choice(targets))
    for char in world.state.characters:
        if char.status == "fallen":
            world.kill(char, "They were left behind.")
    if not world.state.active():
        defeat(world)
        return
    for gid in _combat(world)["groups"]:
        world.state.groups[gid]["attitude"] = "hostile"
    _finish(world)
