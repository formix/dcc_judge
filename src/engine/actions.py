"""
Action resolution (docs/design.md 3, 5 and 11).

A proposal is {"actions": [action, ...]}. Each action is a dict with a "type"
and optional fields: actor, target, item, to, rank, text, silent,
occupation_applies, check, interaction, method, loud, minutes, ops, confirm.

Free actions resolve at once. Timed actions cost minutes (times the leader's
darkness multiplier), run encounter checks first, then apply their results.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from engine import combat, rules
from engine.adventure import parse_item
from engine.catalog import slug
from engine.character import Character
from engine.encounters import pick_encounter
from models.item import Item, text_for
from rulesets.game import MATERIALS, RULES, material

FREE_TYPES = {"look", "examine", "inventory", "status", "leader", "take", "drop", "give", "equip",
              "unequip", "extinguish", "fill", "rank", "talk", "buy", "sell"}
TIMED_TYPES = {"move", "search", "force", "break", "pick_lock", "burn", "interact", "improvise", "wait",
               "repair", "heal", "glean"}
COMBAT_TYPES = {"attack", "defend", "flee"}
ALL_TYPES = FREE_TYPES | TIMED_TYPES | COMBAT_TYPES | {"light"}
NO_ROUND_TYPES = {"look", "examine", "inventory", "status", "leader", "rank", "talk"}
IMPROVISE_OPS = {"transform", "add_furnishing", "record_fact", "set_fire", "consequence"}


class ActionError(Exception):
    """The action cannot be done; nothing was changed and no time passed."""


class NeedsConfirmation(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
        self.index = 0


def _flatten(value: Any) -> Any:
    """Accept {"exit": "x"} or ["x"] where a plain string is expected."""
    while isinstance(value, (dict, list)) and value:
        value = next(iter(value.values())) if isinstance(value, dict) else value[0]
    return value


def validate_proposal(proposal: Any) -> list[str]:
    """Structural checks before anything runs. Normalises lenient shapes in place."""
    errors = []
    if not isinstance(proposal, dict) or not isinstance(proposal.get("actions"), list):
        if isinstance(proposal, dict) and proposal.get("clarify"):
            return []
        return ["The proposal must be an object with an 'actions' list."]
    for action in proposal["actions"]:
        if isinstance(action, dict):
            if "type" not in action:
                for alias in ("action", "kind", "verb", "name"):
                    if isinstance(action.get(alias), str):
                        action["type"] = action.pop(alias)
                        break
            for key in ("target", "item", "to", "actor", "rank", "interaction", "cover"):
                if key in action:
                    action[key] = _flatten(action[key])
                    if action[key] in (False, None, ""):
                        action.pop(key)
    for i, action in enumerate(proposal["actions"]):
        if not isinstance(action, dict):
            errors.append(f"action {i}: must be an object")
            continue
        if "type" not in action:
            errors.append(f"action {i}: every action needs a \"type\" field, e.g. {{\"type\": \"move\", \"target\": \"...\"}}")
        elif action["type"] not in ALL_TYPES:
            errors.append(f"action {i}: unknown type '{action['type']}'. Valid: {sorted(ALL_TYPES)}")
        check = action.get("check")
        if check:
            dc = check.get("dc", RULES["difficulties"].get(str(check.get("difficulty", "")).lower()))
            if dc not in RULES["difficulties"].values():
                errors.append(f"action {i}: check difficulty must be one of {RULES['difficulties']}")
            if check.get("ability") not in ("Strength", "Agility", "Stamina", "Personality", "Intelligence", "Luck"):
                errors.append(f"action {i}: check ability must be a DCC ability")
        for op in action.get("ops", []) or []:
            if op.get("op") not in IMPROVISE_OPS:
                errors.append(f"action {i}: improvise op must be one of {sorted(IMPROVISE_OPS)}")
    return errors


def _norm(text: str) -> str:
    text = re.sub(r"[^a-z0-9' ]+", " ", str(text).lower())
    text = re.sub(r"\b(the|a|an|some|my|his|her|their|its)\b", " ", text)
    return " ".join(text.split())


def resolve_name(text: str, candidates: list[tuple[str, list[str]]]) -> str | None:
    """Match text to a candidate id: exact id or name, then prefix, then word overlap."""
    want = _norm(text)
    if not want:
        return None
    for cid, names in candidates:
        if want == cid.lower() or want in (_norm(n) for n in names if n):
            return cid
    for cid, names in candidates:
        if any(_norm(n).startswith(want) or want.startswith(_norm(n)) for n in names if n and _norm(n)):
            return cid
    words = set(want.split())
    best, score = None, 0
    for cid, names in candidates:
        for n in names:
            overlap = len(words & set(_norm(n).split())) if n else 0
            if overlap > score:
                best, score = cid, overlap
    return best


class Actions:
    def __init__(self, world, level_service: Callable[[int, int, list[str]], int]):
        self.world = world
        self.level_service = level_service

    # ── helpers ─────────────────────────────────────────────────────────────
    @property
    def state(self):
        return self.world.state

    def actor(self, action: dict) -> Character:
        name = action.get("actor")
        if name:
            char = self.world.find_character(str(name))
            if char is None:
                raise ActionError(f"There is no {name} in the party.")
            if not char.active:
                raise ActionError(f"{char.name} cannot act.")
            return char
        return self.world.leader

    def _scene_things(self) -> dict[str, Item]:
        return {o.id: o for o in self.world.visible_objects()}

    def find_thing(self, text: str | None, *, scene: bool = True, party: bool = True) -> Item:
        if not text:
            raise ActionError("Which one?")
        mode = self.world.mode
        pool: dict[str, Item] = {}
        if scene:
            pool.update(self._scene_things())
        if party:
            pool.update({i.id: i for i in self.world.party_items()})
        carried = {p.id for p in self.world.party_items()}
        found = resolve_name(text, [(i.id, [i.label(mode)] + ([i.label("light")] if i.id in carried else []))
                                    for i in pool.values()])
        if found is None:
            raise ActionError(f"You find no '{text}' here.")
        return pool[found]

    def find_exit(self, text: str | None) -> dict:
        exits = self.world.exits()
        if not exits:
            raise ActionError("You find no way out from here.")
        if not text:
            if len(exits) == 1:
                return exits[0]
            raise ActionError("Which way? " + "; ".join(e["label"] for e in exits))
        names = []
        for e in exits:
            labels = [e["label"], e["id"]]
            if e["visited"]:
                scene = self.world.adventure.scenes[e["to"]]
                labels.append(scene.get("name") if isinstance(scene.get("name"), str) else "")
            if e["barrier"]:
                labels.append(self.world.barrier(self.world.adventure.transitions[e["id"]]).label(self.world.mode))
            names.append((e["id"], labels))
        found = resolve_name(text, names)
        if found is None:
            raise ActionError(f"There is no way '{text}'. Ways on: " + "; ".join(e["label"] for e in exits))
        return next(e for e in exits if e["id"] == found)

    def find_enemy(self, text: str | None) -> dict:
        foes = combat.enemies(self.world)
        if not foes:
            raise ActionError("There is no one to fight.")
        if not text:
            return foes[0][1]
        found = resolve_name(text, [(m["id"], [m["name"], self.world.creature(m).get("name", "")]) for _, m in foes])
        if found is None:
            raise ActionError(f"No enemy called '{text}'.")
        return next(m for _, m in foes if m["id"] == found)

    def object_scene(self, item: Item) -> str | None:
        """The scene whose change list holds a fixed object, or None for items."""
        if item.id in self.state.items:
            return None
        if item.id in self.world.fixed_objects(self.state.scene):
            return self.state.scene
        return self.world.adventure.barrier_scene(item.id)

    def set_state(self, item: Item, key: str, value: Any) -> None:
        sid = self.object_scene(item)
        if sid is None:
            item.state[key] = value
        else:
            self.world.change(sid, "set_state", target=item.id, key=key, value=value)
        item.state[key] = value

    def check(self, char: Character, check: dict, ruling_key: str | None = None) -> dict:
        dc = check.get("dc") or RULES["difficulties"][str(check["difficulty"]).lower()]
        if ruling_key:
            saved = self.state.rulings.get(ruling_key)
            if saved is not None and saved > dc:
                dc = saved          # a retry cannot get easier (design 11)
            self.state.rulings[ruling_key] = dc
        result = rules.ability_check(self.world, char, check["ability"], dc, bool(check.get("occupation_applies")))
        self.world.emit("check", result["text"], roll=result)
        return result

    # ── dispatch ────────────────────────────────────────────────────────────
    def run(self, proposal: dict) -> None:
        in_combat = self.state.phase == "combat"
        round_needed = False
        for index, action in enumerate(proposal["actions"]):
            if self.state.phase == "over":
                return
            kind = action["type"]
            if self.state.phase == "combat":
                if kind in ("move", "search", "force", "break", "pick_lock", "burn", "interact", "improvise",
                            "repair", "heal", "buy", "sell", "glean"):
                    raise ActionError(f"You cannot {kind} in the middle of a fight. Attack, defend or flee.")
                if kind not in NO_ROUND_TYPES:
                    round_needed = True
            elif kind in COMBAT_TYPES and kind != "flee":
                if kind == "attack" and self.world.groups_in():
                    self._attack_start(action)
                    in_combat = True
                    round_needed = True
                    continue
                raise ActionError("There is no fight.")
            try:
                getattr(self, f"do_{kind}")(action)
            except NeedsConfirmation as exc:
                exc.index = index
                raise
            if kind == "flee":
                round_needed = False
        if in_combat and round_needed and self.state.phase == "combat":
            combat.resolve_round(self.world)
        self._after_combat_start()

    # ── free actions ────────────────────────────────────────────────────────
    def do_look(self, action):
        self.world.emit("scene", self.world.render_scene())

    def do_examine(self, action):
        target = action.get("target")
        char = self.world.find_character(target) if target else None
        if char:
            self.world.emit("examine", f"{char.name}: {char.race} {char.occupation}, HP {char.hp}/{char.max_hp}, {char.status}.")
            return
        try:
            ex = self.find_exit(target)
            self.world.emit("examine", ex["description"] or ex["label"])
            return
        except ActionError:
            pass
        item = self.find_thing(target)
        mode = "light" if item.id in {i.id for i in self.world.party_items()} else self.world.mode
        text = item.describe(mode) or f"You can tell little about the {item.label(mode)}."
        extra = []
        if item.broken:
            extra.append("It is broken.")
        if item.burning:
            extra.append("It is burning.")
        if item.state.get("patched"):
            extra.append("It is patched and will not last.")
        if "light" in item.rules and item.id in self.state.items:
            extra.append("It is lit." if item.state.get("lit") else "It is not lit.")
        self.world.emit("examine", " ".join([text] + extra))

    def do_inventory(self, action):
        chars = [self.actor(action)] if action.get("actor") else self.state.living()
        for c in chars:
            view = self.world.inventory_view(c)
            self.world.emit("inventory", inventory_text(view), inventory=view)

    def do_status(self, action):
        lines = []
        for c in self.state.characters:
            lead = " (leader)" if c.id == self.state.leader else ""
            vision = ", infravision" if c.infravision else ""
            lines.append(f"{c.name}{lead}: {c.race} {c.occupation}, HP {c.hp}/{c.max_hp}, AC {self.world.ac(c)}, "
                         f"{c.status}, {c.rank} rank{vision}")
        lines += self.world.light_status() or ["No light is burning."]
        lines.append(f"Time: {clock_text(self.state.clock)}.")
        deadline = self.world.deadline_at()
        if deadline is not None:
            left = max(0, deadline - self.state.clock)
            lines.append(f"About {left // 60} hours left." if left >= 60 else "Very little time is left.")
        self.world.emit("status", "\n".join(lines))

    def do_leader(self, action):
        char = self.world.find_character(str(action.get("target", "")))
        if char is None or not char.active:
            raise ActionError("Choose a living, conscious party member to lead.")
        self.state.leader = char.id
        self.world.emit("leader", f"{char.name} now leads the party.")

    def do_rank(self, action):
        char = self.actor(action)
        rank = action.get("rank") or action.get("target")
        if rank not in ("front", "rear"):
            raise ActionError("Rank must be front or rear.")
        char.rank = rank
        self.world.emit("rank", f"{char.name} moves to the {rank} rank.")

    def do_talk(self, action):
        char = self.actor(action)
        self.world.emit("talk", f"{char.name} says: \"{action.get('text', '')}\"")

    def _guard_check(self, item: Item, action: dict) -> bool:
        """Taking a guarded item unseen. Returns False if a fight starts."""
        guard = item.rules.get("guarded_by")
        if not guard:
            return True
        groups = [g for g in self.world.groups_in() if g["group"] == guard and g["attitude"] != "hostile"]
        if not groups:
            return True
        if action.get("silent"):
            result = self._silence(action)
            if result:
                return True
        self.world.emit("noticed", "You are seen!")
        self.state.flags["_start_combat_instances"] = [g["id"] for g in groups]
        return False

    def do_take(self, action):
        char = self.actor(action)
        item = self.find_thing(action.get("target") or action.get("item"), party=False)
        if not item.portable:
            raise ActionError(f"The {item.label(self.world.mode)} cannot be carried.")
        if not self.world.can_carry(char, item):
            raise ActionError(f"{char.name} has no room for the {item.label(self.world.mode)}.")
        if not self._guard_check(item, action):
            return
        self.world.move_item(item.id, {"char": char.id, "slot": "pack"})
        self.world.emit("take", f"{char.name} takes the {item.label(self.world.mode)}.")
        self.world.note(f"{char.name} took the {item.label('light')}.")

    def _held_item(self, text: str | None, char: Character | None = None) -> tuple[Item, Character]:
        """An item the party carries; with `char`, it must be that character's own."""
        if char is not None:
            own = self.world.char_items(char.id)
            found = resolve_name(text or "", [(i.id, [i.label()]) for i in own])
            if found is not None:
                return self.state.items[found], char
        item = self.find_thing(text or "", scene=False)
        holder = self.world.holder(item.id)
        if char and holder and holder.id != char.id:
            raise ActionError(f"{char.name} does not have the {item.label()}; {holder.name} does.")
        return item, holder

    def do_drop(self, action):
        item, holder = self._held_item(action.get("target") or action.get("item"),
                                       self.actor(action) if action.get("actor") else None)
        self.world.move_item(item.id, {"scene": self.state.scene})
        self.world.emit("drop", f"{holder.name} drops the {item.label()}.")
        self.world.note(f"{holder.name} left the {item.label('light')} here.")

    def do_give(self, action):
        item, holder = self._held_item(action.get("target") or action.get("item"))
        to = self.world.find_character(str(action.get("to", "")))
        if to is None or to.status == "dead":
            raise ActionError("Give it to whom?")
        if not self.world.can_carry(to, item):
            raise ActionError(f"{to.name} has no room for it.")
        slot = self.world.location(item.id).get("slot")
        if slot == "hands" and self.world.free_hands(to) >= 1:
            self.world.move_item(item.id, {"char": to.id, "slot": "hands"})
        else:
            self.world.move_item(item.id, {"char": to.id, "slot": "pack"})
        self.world.emit("give", f"{holder.name} gives the {item.label()} to {to.name}.")

    def do_equip(self, action):
        item, holder = self._held_item(action.get("target") or action.get("item"),
                                       self.actor(action) if action.get("actor") else None)
        armor = item.rules.get("armor", {})
        if armor and armor.get("slot") in ("body", "head"):
            slot = "worn"
            for other in self.world.char_items(holder.id, "worn"):
                if other.rules.get("armor", {}).get("slot") == armor["slot"]:
                    self.world.move_item(other.id, {"char": holder.id, "slot": "pack"})
        else:
            slot = "hands"
            need = 2 if item.rules.get("weapon", {}).get("two_handed") else 1
            if self.world.free_hands(holder) < need:
                raise ActionError(f"{holder.name}'s hands are full. Put something away first.")
        self.world.move_item(item.id, {"char": holder.id, "slot": slot})
        self.world.emit("equip", f"{holder.name} {'puts on' if slot == 'worn' else 'takes up'} the {item.label()}.")

    def do_unequip(self, action):
        item, holder = self._held_item(action.get("target") or action.get("item"),
                                       self.actor(action) if action.get("actor") else None)
        if self.world.location(item.id).get("slot") == "pack":
            raise ActionError(f"The {item.label()} is already packed away.")
        self.world.move_item(item.id, {"char": holder.id, "slot": "pack"})
        if not self.world.can_carry(holder, item.copy(quantity=0)) and self.world.slots_used(holder) > RULES["carry"]["slots"]:
            self.world.move_item(item.id, {"scene": self.state.scene})
            self.world.emit("drop", f"{holder.name} has no room and sets the {item.label()} down.")
            return
        self.world.emit("unequip", f"{holder.name} puts away the {item.label()}.")

    def do_extinguish(self, action):
        item = self.find_thing(action.get("target") or "torch")
        if not item.state.get("lit"):
            raise ActionError(f"The {item.label()} is not lit.")
        item.state["lit"] = False
        self.world.emit("light", f"The {item.label()} is put out.")
        if not self.world.party_has_light():
            self.world.on_darkness()

    def do_fill(self, action):
        lamp = self.find_thing(action.get("target") or "lantern", scene=False)
        refill = lamp.rules.get("light", {}).get("refill")
        if not refill:
            raise ActionError(f"The {lamp.label()} takes no fuel.")
        oil = self.world.has_rule(refill)
        if oil is None:
            raise ActionError("You have no oil.")
        self._consume(oil)
        lamp.state["remaining"] = lamp.rules["light"]["minutes"]
        self.world.emit("fill", f"The {lamp.label()} is filled.")

    def _consume(self, item: Item) -> None:
        if item.quantity > 1:
            item.quantity -= 1
        else:
            self.world.remove_item(item.id)

    # ── lighting ────────────────────────────────────────────────────────────
    def _light_target(self, action: dict) -> tuple[Item, Character]:
        text = action.get("target") or action.get("item")
        if text:
            item, holder = self._held_item(text)
        else:
            candidates = [i for i in self.world.party_items() if "light" in i.rules and not i.state.get("lit")]
            if not candidates:
                raise ActionError("You have nothing to light.")
            item = next((i for i in candidates if self.world.location(i.id)["slot"] == "hands"), candidates[0])
            holder = self.world.holder(item.id)
        if "light" not in item.rules:
            raise ActionError(f"The {item.label()} is not a light.")
        if item.state.get("lit"):
            raise ActionError(f"The {item.label()} is already lit.")
        if item.state.get("soaked_until", 0) > self.state.clock:
            raise ActionError(f"The {item.label()} is soaked and will not light yet.")
        if item.rules["light"].get("refill") and item.state.get("remaining", 0) <= 0:
            raise ActionError(f"The {item.label()} has no fuel.")
        if self.world.location(item.id)["slot"] != "hands":
            if self.world.free_hands(holder) < 1:
                raise ActionError(f"{holder.name} needs a free hand to hold a lit {item.label()}.")
        return item, holder

    def _ignite(self, item: Item, holder: Character) -> None:
        if item.quantity > 1:
            item.quantity -= 1
            lit = self.world.add_item(item.copy(quantity=1, state={**item.state, "lit": True}),
                                      {"char": holder.id, "slot": "hands"})
        else:
            item.state["lit"] = True
            self.world.move_item(item.id, {"char": holder.id, "slot": "hands"})
            lit = item
        lit.state.setdefault("remaining", lit.rules["light"]["minutes"])
        self.world.emit("light", f"{holder.name} lights the {item.label()}.")

    def do_light(self, action):
        item, holder = self._light_target(action)
        if self.world.flame_available():
            self._ignite(item, holder)
            return
        starter = self.world.has_rule("fire_starter")
        if starter is None:
            raise ActionError("You have no flame and nothing to strike a light with.")
        if self.state.phase == "combat":
            raise ActionError("There is no time to strike a light in the middle of a fight.")
        striker = self.world.holder(starter.id)

        def resolve():
            result = rules.ability_check(self.world, striker, "Agility", RULES["fire_starter_dc"],
                                         bool(action.get("occupation_applies")))
            self.world.emit("check", "Striking a light: " + result["text"])
            if result["success"]:
                self._ignite(item, holder)
            else:
                self.world.emit("light", "The sparks will not catch.")
        self.timed(action, RULES["fire_starter_minutes"], resolve)

    # ── timed actions ───────────────────────────────────────────────────────
    def _silence(self, action: dict) -> bool:
        cover = self._sound_cover(action)
        if cover:
            self.world.emit("silence", f"You move under cover of the {cover.label(self.world.mode)}.")
            return True
        result = rules.silence_check(self.world, bool(action.get("occupation_applies")))
        self.world.emit("check", result["text"], roll=result)
        return result["success"]

    def _sound_cover(self, action: dict) -> Item | None:
        """Clever silent movement: an active source of noise named in the action."""
        cover_name = action.get("cover")
        if not cover_name:
            return None
        try:
            item = self.find_thing(cover_name, party=False)
        except ActionError:
            return None
        rule = item.rules.get("sound_cover")
        if not rule:
            return None
        when = rule.get("when") if isinstance(rule, dict) else None
        if when and not self.world._condition_met(when, self.state.scene):
            return None
        return item

    def timed(self, action: dict, base_minutes: int, resolve: Callable[[], None],
              loud: bool = False, silent_success: bool | None = None, travel: bool = False) -> bool:
        """Run a timed action: noise, encounter checks, time, then its result.

        Travel between the village and an adventure has no encounter checks and
        burns no torch time. Returns False if an encounter interrupted it.
        """
        w = self.world
        if travel:
            w.advance(base_minutes, travel=True)
            resolve()
            return True
        enc = self.state.encounter
        start = enc["start"]
        minutes = base_minutes * w.time_multiplier()
        pre = []
        if loud and not silent_success:
            pre.append("loud")
        replaced_fade = False
        if silent_success and not loud:
            pre.append("silent")
            replaced_fade = True
        if pre:
            enc["level"] = self.level_service(enc["level"], start, pre)
        if loud and silent_success:
            w.emit("silence", "You manage it without a sound.")
        rolls_encounters = self._encounters_possible()
        interrupted_at = None
        if rolls_encounters:
            carry = enc["carry"]
            for i in range((carry + minutes) // 10):
                if w.dice.die(6) <= enc["level"]:
                    interrupted_at = (i + 1) * 10 - carry
                    break
            enc["carry"] = 0 if interrupted_at is not None else (carry + minutes) % 10
        elapsed = interrupted_at if interrupted_at is not None else minutes
        lit = w.party_has_light()
        w.advance(elapsed)
        if self.state.phase == "over":
            return False
        if interrupted_at is None:
            resolve()
        if rolls_encounters:
            post = []
            if not lit:
                enc["dark"] += elapsed
                post += ["dark_10"] * (enc["dark"] // 10)
                enc["dark"] %= 10
            elif loud and not silent_success:
                enc["quiet"] = 0
            elif not replaced_fade:
                enc["quiet"] += elapsed
                post += ["quiet_light_10"] * (enc["quiet"] // 10)
                enc["quiet"] %= 10
            if post:
                enc["level"] = self.level_service(enc["level"], start, post)
        if interrupted_at is not None:
            w.emit("interrupted", "Before you can finish, something happens.")
            self.trigger_encounter()
            return False
        return True

    def _encounters_possible(self) -> bool:
        scene = self.world.scene
        return bool(self.world.adventure.encounters.get("table")) and not scene.get("safe") \
            and scene.get("encounters", "inherit") != "none" and self.state.phase == "exploration"

    def trigger_encounter(self) -> None:
        w = self.world
        entry = pick_encounter(w.dice, w.adventure.encounters["table"], self.state.spent_encounters)
        if entry is None:
            w.emit("encounter", "You hear something in the dark, but nothing comes.")
            return
        self.state.spent_encounters[entry["id"]] = self.state.spent_encounters.get(entry["id"], 0) + 1
        text = text_for(entry.get("text"), w.mode) if entry.get("text") else None
        if text:
            w.emit("encounter", text)
        if entry.get("effects"):
            w.run_effects(entry["effects"], w.leader)
        if entry.get("group"):
            group = w.spawn_group(entry["group"], self.state.scene, entry.get("attitude"))
            if group["attitude"] == "hostile":
                surprised = w.dice.die(6) <= RULES["surprise"][w.mode]
                combat.start(w, [group["id"]], party_surprised=surprised)
            else:
                w.emit("encounter", w.group_text(group, w.mode))

    def do_wait(self, action):
        self.timed(action, RULES["action_minutes"]["wait"], lambda: self.world.emit("wait", "Time passes."))

    # movement ---------------------------------------------------------------
    def do_move(self, action):
        w = self.world
        ex = self.find_exit(action.get("target"))
        t = w.adventure.transitions[ex["id"]]
        passable, reason = w.passable(t)
        if not passable:
            raise ActionError(reason.capitalize() + ".")
        barrier = w.barrier(t)
        loud = False
        if barrier is not None and reason == "unlock":
            self.set_state(barrier, "locked", False)
            w.emit("unlock", f"You unlock the {barrier.label(w.mode)}.")
        if barrier is not None and w.barrier_state(barrier) == "closed":
            noisy = barrier.rules.get("noisy")
            if noisy and not barrier.state.get(noisy.get("unless", "oiled")):
                loud = True
            self.set_state(barrier, "open", True)
        silent = self._silence(action) if action.get("silent") else None
        if loud and silent is not True:
            w.emit("noise", f"The {barrier.label(w.mode)} groans loudly on its hinges.")
        self._first_torch()
        minutes = t.get("minutes", RULES["action_minutes"]["move"])
        origin = self.state.scene
        if t.get("travel") and w.in_village:
            w.start_deadline()   # design 13: the clock starts when the party first sets out

        def resolve():
            self._spring_traps(t)
            if self.state.phase == "over":
                return
            if loud and silent is not True:
                self._wake_unaware(origin)
            self.state.scene = ex["to"]
            if t.get("on_traverse"):
                w.run_effects(t["on_traverse"], w.leader)
            self.enter_scene(silent=bool(silent))
        self.timed(action, minutes, resolve, loud=loud, silent_success=silent, travel=bool(t.get("travel")))

    def _first_torch(self) -> None:
        """Design 6.2: the first torch lights free while still outside in daylight."""
        w = self.world
        if not w.scene.get("entrance") or self.state.flags.get("_first_torch") or w.carried_light_sources():
            return
        lights = [i for i in w.party_items() if "light" in i.rules and not i.rules["light"].get("refill")
                  and i.state.get("soaked_until", 0) <= self.state.clock]
        lights.sort(key=lambda i: "torch" not in i.label().lower())   # torches first
        torch = lights[0] if lights else None
        if torch is None or w.has_rule("fire_starter") is None:
            return
        holder = next((c for c in [w.leader] + w.state.active() if w.free_hands(c) >= 1), None)
        if holder is None:
            return
        self.state.flags["_first_torch"] = True
        if w.holder(torch.id).id != holder.id:
            if torch.quantity > 1:
                torch.quantity -= 1
                torch = w.add_item(torch.copy(quantity=1), {"char": holder.id, "slot": "pack"})
            else:
                w.move_item(torch.id, {"char": holder.id, "slot": "pack"})
        self._ignite(torch, holder)

    def _spring_traps(self, transition: dict) -> None:
        w = self.world
        for sid in (transition["from"], transition["to"]):
            for trap in w.adventure.scenes[sid].get("traps", []):
                if transition["id"] not in trap.get("trigger", {}).get("move", []):
                    continue
                if self.state.flags.get(f"_trap_disarmed:{trap['id']}"):
                    continue
                if trap["id"] in self.state.discovered:
                    w.emit("trap", text_for(trap.get("avoided_text"), w.mode) or "You step around the trap you found.")
                    continue
                w.emit("trap", text_for(trap.get("text"), w.mode) or "A trap springs!")
                w.run_effects(trap.get("effects", []), w.leader, sid, trap["id"])
                if trap.get("once"):
                    self.state.flags[f"_trap_disarmed:{trap['id']}"] = True

    def _wake_unaware(self, scene_id: str) -> None:
        for g in self.world.groups_in(scene_id):
            if g["attitude"] == "unaware":
                g["attitude"] = "hostile"
                self.world.emit("noticed", "Something has heard you.")

    def enter_scene(self, silent: bool = False) -> None:
        """Design 3.1: passive checks and the scene description on every entry."""
        w = self.world
        sid = self.state.scene
        if sid not in self.state.visited:
            self.state.visited.append(sid)
        w.ensure_scene_groups(sid)
        self._passive_checks()
        w.emit("scene", w.render_scene())
        hostile = [g for g in w.groups_in() if g["attitude"] == "hostile"]
        unaware = [g for g in w.groups_in() if g["attitude"] == "unaware"]
        if unaware and not silent:
            for g in unaware:
                g["attitude"] = "hostile"
            w.emit("noticed", "You have been noticed!")
            hostile += unaware
        elif unaware:
            w.emit("unnoticed", "They have not noticed you.")
        if hostile:
            combat.start(w, [g["id"] for g in hostile], enemies_surprised=silent and not unaware)

    def _hidden_here(self) -> list[tuple[str, dict, str]]:
        """(id, hidden spec, label) for undiscovered things in this scene."""
        w = self.world
        sid = self.state.scene
        out = []
        for obj in list(w.fixed_objects(sid).values()) + w.scene_items(sid):
            if w.is_hidden(obj.id, obj.hidden):
                out.append((obj.id, obj.hidden, obj.label("light")))
        for t in w.adventure.transitions.values():
            if sid in (t["from"], t["to"]) and w.is_hidden(t["id"], t.get("hidden")):
                label = (t.get("ends") or {}).get(sid, {}).get("label", "a hidden way")
                out.append((t["id"], t["hidden"], label if isinstance(label, str) else "a hidden way"))
        for trap in w.scene.get("traps", []):
            if trap.get("hidden") and trap["id"] not in self.state.discovered:
                out.append((trap["id"], trap["hidden"], trap.get("name", "a trap")))
        return out

    def _passive_checks(self) -> None:
        w = self.world
        for thing_id, hidden, label in self._hidden_here():
            passive = hidden.get("passive")
            if not passive:
                continue
            races = passive.get("races")
            for char in w.state.active():
                if races and char.race not in races:
                    continue
                result = rules.perception_check(w, char, passive.get("dc", 15), hidden.get("kind", "search"))
                if result["success"]:
                    w.discover(thing_id)
                    w.emit("discover", f"{char.name} notices {label}.")
                    break

    # search -----------------------------------------------------------------
    def do_search(self, action):
        w = self.world
        char = self.actor(action)
        target_text = action.get("target")
        target_id = None
        if target_text and _norm(target_text) not in ("room", "area", "here", "around", "everywhere"):
            try:
                target_id = self.find_thing(target_text, party=False).id
            except ActionError:
                target_id = self.find_exit(target_text)["id"]

        def resolve():
            found_any = False
            if target_id:
                obj = self._scene_things().get(target_id)
                if obj is not None and obj.rules.get("search_text"):
                    w.emit("search", text_for(obj.rules["search_text"], w.mode_for(char)) or "")
                    found_any = True
            for thing_id, hidden, label in self._hidden_here():
                find = hidden.get("find")
                if target_id and find == target_id:
                    dc = hidden.get("dc")
                elif not target_id and hidden.get("area_dc", RULES["default_search_dc"]) is not None:
                    dc = hidden.get("area_dc", RULES["default_search_dc"])
                else:
                    continue
                if dc is not None:
                    result = rules.perception_check(w, char, dc, hidden.get("kind", "search"))
                    w.emit("check", result["text"], roll=result)
                    if not result["success"]:
                        continue
                w.discover(thing_id)
                found_any = True
                w.emit("discover", text_for(hidden.get("text"), w.mode_for(char)) or f"{char.name} finds {label}.")
            if not found_any:
                w.emit("search", f"{char.name} searches and finds nothing new.")
        minutes = RULES["action_minutes"]["search"]
        self.timed(action, minutes, resolve)

    # force, break, pick, burn, repair ---------------------------------------
    def _target_object(self, action: dict) -> Item:
        text = action.get("target")
        try:
            return self.find_thing(text)
        except ActionError:
            ex = self.find_exit(text)
            barrier = self.world.barrier(self.world.adventure.transitions[ex["id"]])
            if barrier is None:
                raise ActionError("There is nothing there to force.")
            return barrier

    def _can_break(self, item: Item, char: Character) -> None:
        if item.rules.get("unbreakable"):
            raise ActionError(f"The {item.label(self.world.mode)} cannot be broken.")
        if item.broken:
            raise ActionError(f"The {item.label(self.world.mode)} is already broken.")
        need = material(item.material)["break"]
        if need != "anyone":
            tools = [i for i in self.world.party_items() if set(i.rules.get("breaks", [])) & set(need)]
            if not tools:
                raise ActionError(f"Nothing you carry can break {item.material}.")

    def do_force(self, action):
        self._break_like(action, verb="force")

    def do_break(self, action):
        self._break_like(action, verb="break")

    def _break_like(self, action: dict, verb: str):
        char = self.actor(action)
        item = self._target_object(action)
        self._can_break(item, char)
        dc = item.rules.get("locked", {}).get("force_dc") if verb == "force" else None
        dc = dc or item.rules.get("break_dc") or material(item.material)["dc"]
        check = action.get("check") or {"ability": "Strength", "dc": dc,
                                        "occupation_applies": action.get("occupation_applies", False)}
        check = {**check, "dc": max(dc, check.get("dc") or 0)}

        def resolve():
            result = self.check(char, check, f"{char.id}|{item.id}|{verb}")
            if result["success"]:
                self.set_state(item, "integrity", "broken")
                if item.rules.get("broken_description"):
                    self.set_description(item, item.rules["broken_description"])
                self.world.emit(verb, f"{char.name} {'forces' if verb == 'force' else 'breaks'} the {item.label(self.world.mode)}.")
                self.world.note(f"{char.name} broke the {item.label('light')}.")
            else:
                self.world.emit(verb, f"The {item.label(self.world.mode)} holds.")
        self.timed(action, RULES["action_minutes"][verb], resolve, loud=True)

    def set_description(self, item: Item, description) -> None:
        sid = self.object_scene(item)
        if sid is None:
            item.state["description"] = description
        else:
            self.world.change(sid, "set_description", target=item.id, description=description)

    def do_pick_lock(self, action):
        char = self.actor(action)
        item = self._target_object(action)
        lock = item.rules.get("locked")
        if not lock or not item.state.get("locked", True):
            raise ActionError(f"The {item.label(self.world.mode)} is not locked.")
        if self.world.has_rule("lockpicks", char) is None:
            raise ActionError(f"{char.name} has no tools to pick a lock.")
        check = {"ability": "Agility", "dc": lock.get("pick_dc", 15),
                 "occupation_applies": action.get("occupation_applies", False)}

        def resolve():
            if self.check(char, check, f"{char.id}|{item.id}|pick")["success"]:
                self.set_state(item, "locked", False)
                self.world.emit("pick_lock", f"The lock of the {item.label(self.world.mode)} clicks open.")
            else:
                self.world.emit("pick_lock", "The lock defeats you.")
        self.timed(action, RULES["action_minutes"]["pick_lock"], resolve)

    def do_burn(self, action):
        char = self.actor(action)
        item = self._target_object(action)
        self._set_fire(item, char, action)

    def _set_fire(self, item: Item, char: Character, action: dict) -> None:
        if not material(item.material)["combustible"]:
            raise ActionError(f"The {item.label(self.world.mode)} will not burn.")
        if item.burning or item.state.get("fire") == "burnt":
            raise ActionError(f"The {item.label(self.world.mode)} has already burned.")
        if not self.world.flame_available():
            raise ActionError("You need a flame.")

        def resolve():
            self.set_state(item, "fire", "burning")
            size = item.rules.get("size", "medium")
            sid = self.object_scene(item) or self.state.scene
            self.world.schedule(RULES["burn_minutes"][size], [
                {"op": "set_state", "target": item.id, "key": "fire", "value": "burnt"},
                {"op": "set_state", "target": item.id, "key": "integrity", "value": "broken"},
            ], sid, item.id)
            self.world.emit("burn", f"The {item.label(self.world.mode)} catches fire.")
            self.world.note(f"{char.name} set the {item.label('light')} on fire.")
        self.timed(action, RULES["action_minutes"]["burn"], resolve)

    def do_repair(self, action):
        char = self.actor(action)
        item = self.find_thing(action.get("target"), scene=False)
        if not item.broken:
            raise ActionError(f"The {item.label()} is not broken.")
        if item.state.get("unusable"):
            raise ActionError(f"The {item.label()} is beyond repair.")

        def resolve():
            item.state["integrity"] = "intact"
            item.state["patched"] = True
            self.world.emit("repair", f"{char.name} patches the {item.label()}. It will hold for one more use.")
        self.timed(action, RULES["action_minutes"]["repair_quick"], resolve)

    # the tavern -------------------------------------------------------------
    def do_glean(self, action):
        """Design 13: gleaning rumors in the tavern reveals the adventure's hook first."""
        w = self.world
        if not w.scene.get("rumors"):
            raise ActionError("There is no one here to trade gossip with.")
        hook = w.adventure.hook

        def resolve():
            if not self.state.flags.get("hook_revealed"):
                self.state.flags["hook_revealed"] = True
                w.discover("village_road")
                w.emit("hook", text_for(hook["text"], w.mode) or str(hook["text"]))
                self.state.facts.append(w.fill(f"Hook: the way to {hook['destination']} is open."))
                return
            index = self.state.flags.get("rumor_index", 0)
            rumors = w.adventure.rumors
            if index >= len(rumors):
                w.emit("rumor", "You hear nothing you have not heard before.")
                return
            self.state.flags["rumor_index"] = index + 1
            rumor = rumors[index]
            w.emit("rumor", text_for(rumor, w.mode) or str(rumor))
        self.timed(action, RULES["action_minutes"]["glean"], resolve)

    # healing and trade ------------------------------------------------------
    def do_heal(self, action):
        char = self.actor(action)
        patient = self.world.find_character(str(action.get("target") or char.name))
        if patient is None or patient.status != "ok":
            raise ActionError("Heal whom? Only the living and conscious can be tended.")
        if patient.hp >= patient.max_hp:
            raise ActionError(f"{patient.name} is not hurt.")
        supplies = self.world.has_rule("dressing")
        if supplies is None:
            raise ActionError("You have no healing supplies.")

        def resolve():
            self._consume(supplies)
            amount = self.world.dice.roll(RULES["healing"]["dressing_hp"]).total
            patient.hp = min(patient.max_hp, patient.hp + amount)
            self.world.emit("heal", f"{char.name} binds {patient.name}'s wounds: +{amount} HP ({patient.hp}/{patient.max_hp}).")
        self.timed(action, RULES["action_minutes"]["heal"], resolve)

    def _shop(self) -> dict:
        shop = self.world.scene.get("shop")
        if not shop:
            raise ActionError("There is no one to trade with here.")
        return shop

    def _pay(self, char: Character, price: int) -> list[tuple[Character, int]]:
        """Pay from the buyer's purse, then from the others' (pooled savings, design 8.2).
        Returns who paid how much."""
        payers = [char] + [c for c in self.state.living() if c.id != char.id]
        if sum(c.cp for c in payers) < price:
            raise ActionError(f"The party cannot afford that ({price} cp).")
        paid = []
        for c in payers:
            share = min(c.cp, price)
            if share:
                c.cp -= share
                price -= share
                paid.append((c, share))
            if price == 0:
                break
        return paid

    def do_buy(self, action):
        from engine.catalog import make_item
        shop = self._shop()
        char = self.actor(action)
        stock = {s: None for s in shop.get("stock", [])}
        for custom in shop.get("custom", []):
            stock[custom["name"]["light"] if isinstance(custom["name"], dict) else custom["name"]] = custom
        name = resolve_name(str(action.get("target", "")), [(s, [s]) for s in stock])
        if name is None:
            raise ActionError("The shop has no such thing. It sells: " + ", ".join(stock))
        qty = max(1, int(action.get("quantity", 1)))
        limit = shop.get("limited", {}).get(name)
        sold = self.state.flags.get(f"_sold:{name}", 0)
        if limit is not None and sold + qty > limit:
            raise ActionError(f"Only {max(0, limit - sold)} left.")
        if stock[name] is None:
            item = make_item(name, qty)
        else:
            item = parse_item({**stock[name], "quantity": qty})
        price = item.cost_cp * qty
        if not self.world.can_carry(char, item):
            raise ActionError(f"{char.name} has no room for that.")
        paid = self._pay(char, price)
        self.state.flags[f"_sold:{name}"] = sold + qty
        self.world.add_item(item, {"char": char.id, "slot": "pack"})
        helpers = [f"{c.name} adds {share} cp" for c, share in paid if c.id != char.id]
        self.world.emit("buy", f"{char.name} buys {qty} {name} for {price} cp"
                        + (f" ({'; '.join(helpers)})." if helpers else "."))

    def do_sell(self, action):
        """The named character sells one of their own items; the leader if no one is named."""
        self._shop()
        item, holder = self._held_item(action.get("target") or action.get("item"), self.actor(action))
        goal = self.world.adventure.data.get("goal", {}).get("items", [])
        if item.id.split("-")[0] in goal or item.rules.get("magic") or item.broken:
            raise ActionError(f"The shopkeeper will not take the {item.label()}.")
        value = item.cost_cp * item.quantity
        rate = RULES["shop"]["sell_base"]
        if action.get("negotiate"):
            key = f"_negotiated:{item.id}"
            if key in self.state.flags:
                rate = self.state.flags[key]
            else:
                result = rules.ability_check(self.world, holder, RULES["shop"]["negotiation_ability"], 0,
                                             bool(action.get("occupation_applies")))
                rate = next(b["rate"] for b in RULES["shop"]["negotiation_bands"] if result["total"] >= b["min_total"])
                self.state.flags[key] = rate
                self.world.emit("check", f"Haggling: {holder.name} rolls {result['total']}; the offer is {int(rate * 100)}%.")
        offer = int(value * rate)
        if action.get("negotiate") and not action.get("confirm"):
            raise NeedsConfirmation(f"The shopkeeper offers {offer} cp for the {item.label()}. Sell?")
        holder.cp += offer
        self.world.remove_item(item.id)
        self.world.emit("sell", f"{holder.name} sells the {item.label()} for {offer} cp.")

    # authored interactions --------------------------------------------------
    def do_interact(self, action):
        char = self.actor(action)
        item = self._target_object(action)
        wanted = action.get("interaction")
        inter = next((i for i in item.interactions if i["id"] == wanted or wanted in i.get("verbs", [])), None)
        if inter is None:
            choices = ", ".join(i["id"] for i in item.interactions) or "none"
            raise ActionError(f"You cannot do that with the {item.label(self.world.mode)}. Possible: {choices}.")
        if inter.get("once") and self.state.flags.get(f"_done:{item.id}:{inter['id']}"):
            raise ActionError("That has already been done.")
        if not self.world._condition_met(inter.get("when"), self.state.scene):
            raise ActionError(text_for(inter.get("refuse_text"), self.world.mode) or "That will not work now.")
        needed = None
        if inter.get("requires_rule"):
            needed = self.world.has_rule(inter["requires_rule"])
            if needed is None:
                raise ActionError(text_for(inter.get("missing_text"), self.world.mode) or "You lack what that needs.")
        if inter.get("confirm") and not action.get("confirm"):
            raise NeedsConfirmation(text_for(inter.get("confirm_text"), "light") or f"Really {inter['id']}?")

        def resolve():
            if inter.get("check"):
                result = self.check(char, {**inter["check"], "occupation_applies": action.get("occupation_applies",
                                    inter["check"].get("occupation_applies", False))}, f"{char.id}|{item.id}|{inter['id']}")
                if not result["success"]:
                    self.world.emit("interact", text_for(inter.get("failure_text"), self.world.mode) or "It does not work.")
                    self.world.run_effects(inter.get("on_failure", []), char, None, item.id)
                    return
            if needed is not None and inter.get("consumes"):
                self._consume(needed)
            self.state.flags[f"_done:{item.id}:{inter['id']}"] = True
            if inter.get("text"):
                self.world.emit("interact", text_for(inter["text"], self.world.mode) or "")
            self.world.run_effects(inter.get("effects", []), char, None, item.id)
        minutes = inter.get("minutes", RULES["action_minutes"]["interact"])
        if minutes == 0:
            resolve()
        else:
            self.timed(action, minutes, resolve, loud=bool(inter.get("loud")))

    # improvised actions (the Judge's checked operations, design 2.2) --------
    def do_improvise(self, action):
        char = self.actor(action)
        ops = action.get("ops") or []
        minutes = int(action.get("minutes", RULES["action_minutes"]["improvise"]))
        if minutes < 0 or minutes > 60:
            raise ActionError("An improvised action takes between 0 and 60 minutes.")
        if minutes == 0 and any(op["op"] not in ("add_furnishing", "record_fact") for op in ops):
            raise ActionError("Only adding a furnishing or recording a fact can be free.")
        if minutes == 0 and action.get("check"):
            raise ActionError("Anything needing a roll takes time.")
        plan = [self._prepare_op(op, char) for op in ops]
        method = slug(str(action.get("method", "improvise")))[:40]
        target = next((op.get("source") or op.get("target") for op in ops if op.get("source") or op.get("target")), "")

        def resolve():
            if action.get("check"):
                result = self.check(char, action["check"], f"{char.id}|{target}|{method}")
                if not result["success"]:
                    self.world.emit("improvise", "It does not work.")
                    for op in ops:
                        if op["op"] == "consequence":
                            severity = op.get("on_failure", {}).get("damage")
                            if severity in RULES["hazards"]:
                                self.world.hurt(char, self.world.dice.roll(RULES["hazards"][severity]).total, op.get("text", ""))
                    return
            for fn in plan:
                fn()
        if minutes == 0:
            resolve()
        else:
            self.timed(action, minutes, resolve, loud=bool(action.get("loud")))

    def _prepare_op(self, op: dict, char: Character) -> Callable[[], None]:
        w = self.world
        kind = op["op"]
        if kind == "record_fact":
            return lambda: (self.state.facts.append(str(op["text"])), w.emit("fact", str(op["text"])))
        if kind == "consequence":
            return lambda: None
        if kind == "add_furnishing":
            if w.scene.get("closed"):
                raise ActionError("Nothing more can be found here.")
            desc = op.get("description")
            if not isinstance(desc, dict) or not all(desc.get(m) for m in ("light", "infravision", "touch")):
                raise ActionError("A furnishing needs light, infravision and touch descriptions.")
            if op.get("material", "misc") not in MATERIALS:
                raise ActionError(f"Unknown material '{op.get('material')}'.")
            item = Item(id=slug(op["name"]), name={"light": op["name"], "infravision": op.get("shape_name", op["name"]),
                                                    "touch": op.get("touch_name", op["name"])},
                        description=desc, material=op.get("material", "misc"), portable=bool(op.get("portable", False)))

            def add():
                new = item.copy(id=self.state.new_id(item.id))
                if new.portable:
                    w.add_item(new, {"scene": self.state.scene})
                else:
                    w.change(self.state.scene, "add", item=new.to_dict())
                w.emit("furnishing", f"There is {op['name']} here.")
            return add
        if kind == "set_fire":
            item = self.find_thing(op.get("target"))
            return lambda: self._set_fire_now(item, char)
        if kind == "transform":
            source = self.find_thing(op.get("source"))
            self._can_break(source, char)
            creates = []
            for c in op.get("creates", []):
                rules_ = {}
                if c.get("weapon"):
                    if c["weapon"] not in RULES["improvised_weapons"]:
                        raise ActionError(f"Weapon category must be one of {sorted(RULES['improvised_weapons'])}.")
                    rules_["weapon"] = {"damage": RULES["improvised_weapons"][c["weapon"]], "melee": True,
                                        "improvised": True}
                    if c["weapon"] == "two_handed":
                        rules_["weapon"]["two_handed"] = True
                name = c["name"]
                creates.append(Item(id=slug(name), name={"light": name, "infravision": name, "touch": name},
                                    description=c.get("description") or {"light": name, "infravision": name, "touch": name},
                                    material=c.get("material", source.material), rules=rules_, portable=True))

            def transform():
                self.set_state(source, "integrity", "broken")
                if op.get("description"):
                    self.set_description(source, op["description"])
                for new in creates:
                    added = w.add_item(new, {"scene": self.state.scene})
                    w.emit("transform", f"{char.name} now has a {added.label()} to hand; it lies ready.")
                w.note(f"{char.name} broke the {source.label('light')}.")
            return transform
        raise ActionError(f"Unknown operation {kind}")

    def _set_fire_now(self, item: Item, char: Character) -> None:
        if not material(item.material)["combustible"] or item.state.get("fire"):
            self.world.emit("burn", f"The {item.label(self.world.mode)} will not burn.")
            return
        self.set_state(item, "fire", "burning")
        self.world.schedule(RULES["burn_minutes"][item.rules.get("size", "medium")], [
            {"op": "set_state", "target": item.id, "key": "fire", "value": "burnt"},
            {"op": "set_state", "target": item.id, "key": "integrity", "value": "broken"},
        ], self.object_scene(item) or self.state.scene, item.id)
        self.world.emit("burn", f"The {item.label(self.world.mode)} catches fire.")

    # ── combat actions ──────────────────────────────────────────────────────
    def _attack_start(self, action: dict) -> None:
        groups = self.world.groups_in()
        surprised_enemies = all(g["attitude"] in ("unaware", "neutral") for g in groups)
        combat.start(self.world, [g["id"] for g in groups], enemies_surprised=surprised_enemies)
        self.do_attack(action)

    def do_attack(self, action):
        char = self.actor(action)
        target = self.find_enemy(action.get("target"))
        combat.set_order(self.world, char, {"type": "attack", "target": target["id"]})
        if action.get("all"):
            for other in self.state.active():
                combat.set_order(self.world, other, {"type": "attack", "target": target["id"]})

    def do_defend(self, action):
        char = self.actor(action)
        combat.set_order(self.world, char, {"type": "defend"})
        self.world.emit("defend", f"{char.name} stays on guard.")

    def do_flee(self, action):
        if self.state.phase != "combat":
            raise ActionError("There is nothing to flee from.")
        ex = self.find_exit(action.get("target"))
        t = self.world.adventure.transitions[ex["id"]]
        passable, reason = self.world.passable(t)
        if not passable:
            raise ActionError(reason.capitalize() + ".")
        fallen = [c for c in self.state.characters if c.status == "fallen"]
        if fallen and not action.get("confirm"):
            names = ", ".join(c.name for c in fallen)
            raise NeedsConfirmation(f"Fleeing now leaves {names} behind unchecked: they will die. Flee anyway?")
        combat.flee(self.world, ex)
        if self.state.phase == "over":
            return
        self.state.scene = ex["to"]
        self.enter_scene()

    def _after_combat_start(self) -> None:
        """Start fights requested by effects or by being seen."""
        flags = self.state.flags
        ids = flags.pop("_start_combat_instances", None)
        group = flags.pop("_start_combat", None)
        if group and self.state.phase == "exploration":
            ids = [self.world.spawn_group(group, self.state.scene)["id"]]
        if ids and self.state.phase == "exploration":
            combat.start(self.world, ids)


def _item_text(entry: dict) -> str:
    text = entry["name"] + (f" x{entry['quantity']}" if entry.get("quantity", 1) > 1 else "")
    notes = [n for n, on in (("lit, " + entry.get("light", ""), entry.get("lit")), ("broken", entry.get("broken")),
                             ("patched", entry.get("patched"))) if on]
    return text + (f" ({'; '.join(notes)})" if notes else "")


def inventory_text(view: dict) -> str:
    """Plain list of a character's belongings, from World.inventory_view."""
    eq = view["equipment"]
    lines = [f"{view['name']}{' (leader)' if view['leader'] else ''}"]
    for n, hand in enumerate(eq["hands"], 1):
        lines.append(f"  Hand {n}: {_item_text(hand) if hand and 'same_as' not in hand else (hand['name'] if hand else '-')}")
    lines.append(f"  Body: {_item_text(eq['body']) if eq['body'] else '-'}")
    lines.append(f"  Head: {_item_text(eq['head']) if eq['head'] else '-'}")
    lines.append(f"  Pack ({view['slots']['used']}/{view['slots']['total']} slots, {view['slots']['free']} free):")
    for item in view["pack"]:
        lines.append(f"    - {_item_text(item)} [{item['slots']} slot{'s' if item['slots'] != 1 else ''}]")
    lines.append(f"    - {view['coins']['cp']} cp [{view['coins']['slots']} slot{'s' if view['coins']['slots'] != 1 else ''}]")
    return "\n".join(lines)


def clock_text(minutes: int) -> str:
    return f"hour {minutes // 60}, minute {minutes % 60:02d}"
