"""
World: queries and changes over an Adventure and a GameState.

Everything the Judge sees is built here from what the party can perceive
(docs/design.md 2.3 and 6.4). Every change to the game goes through World so
the save stays consistent.
"""

from __future__ import annotations

import math
from typing import Any

from engine.adventure import Adventure, parse_item
from engine.character import Character
from engine.dice import Dice
from engine.state import GameState
from models.item import Item, text_for
from rulesets.dcc import RECOVER_BODY_WINDOW_MINUTES
from rulesets.game import RULES, light_stage, material


def money_text(cp: int) -> str:
    """Copper pieces as gold, silver and copper: 1 gp = 100 cp, 1 sp = 10 cp."""
    gp, rest = divmod(max(0, cp), 100)
    sp, cp_left = divmod(rest, 10)
    parts = [f"{n} {unit}" for n, unit in ((gp, "gp"), (sp, "sp"), (cp_left, "cp")) if n]
    return " ".join(parts) or "0 cp"


def label_text(value, mode: str) -> str | None:
    """Labels and names: a plain string is used in every perception mode."""
    if isinstance(value, str):
        return value
    return text_for(value, mode)


class World:
    def __init__(self, adventure: Adventure, state: GameState, dice: Dice):
        self.adventure = adventure
        self.state = state
        self.dice = dice
        self.events: list[dict[str, Any]] = []

    # ── events ──────────────────────────────────────────────────────────────
    def emit(self, kind: str, text: str, **data: Any) -> None:
        self.events.append({"kind": kind, "text": self.fill(text), **data})

    def fill(self, value: Any) -> Any:
        """Replace {village}, {tavern} and {destination} in text, recursively."""
        if isinstance(value, str):
            if "{" not in value:
                return value
            names = {"village": self.state.village.get("name", "the village"),
                     "tavern": self.state.village.get("tavern", "the tavern"),
                     "destination": self.adventure.hook.get("destination", "the wilds")}
            for key, name in names.items():
                value = value.replace("{" + key + "}", name)
            return value
        if isinstance(value, dict):
            return {k: self.fill(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.fill(v) for v in value]
        return value

    def available_actions(self) -> list[dict[str, str]]:
        """The scene's menu of actions, for scenes that list them (design 13)."""
        return [{"label": self.fill(m["label"]), "command": m["command"]}
                for m in self.scene.get("menu", []) if self._condition_met(m.get("when"), self.state.scene)]

    @property
    def in_village(self) -> bool:
        return bool(self.scene.get("village"))

    def deadline_at(self) -> int | None:
        """Game minute of the adventure's deadline, once it has started."""
        deadline = self.adventure.data.get("deadline")
        if isinstance(deadline, int):
            return deadline
        return self.state.flags.get("deadline_at")

    def start_deadline(self) -> None:
        deadline = self.adventure.data.get("deadline")
        if isinstance(deadline, dict) and "deadline_at" not in self.state.flags:
            self.state.flags["deadline_at"] = self.now + deadline["minutes"]

    @property
    def now(self) -> int:
        return self.state.clock

    @property
    def scene(self) -> dict[str, Any]:
        return self.adventure.scenes[self.state.scene]

    # ── fixed objects and scene changes ─────────────────────────────────────
    def change(self, scene_id: str, op: str, **data: Any) -> None:
        self.state.scene_changes.setdefault(scene_id, []).append({"turn": self.state.turn, "op": op, **data})

    def fixed_objects(self, scene_id: str) -> dict[str, Item]:
        objects = {k: v.copy() for k, v in self.adventure.objects.get(scene_id, {}).items()}
        for ch in self.state.scene_changes.get(scene_id, []):
            op = ch["op"]
            target = objects.get(ch.get("target", ""))
            if op == "set_state" and target:
                target.state[ch["key"]] = ch["value"]
            elif op == "set_description" and target:
                target.state["description"] = ch["description"]
            elif op == "add":
                item = Item.from_dict(ch["item"])
                objects[item.id] = item
            elif op == "remove":
                objects.pop(ch["target"], None)
        return objects

    def history(self, scene_id: str) -> list[str]:
        return [ch["text"] for ch in self.state.scene_changes.get(scene_id, []) if ch["op"] == "note"]

    def note(self, text: str, scene_id: str | None = None) -> None:
        self.change(scene_id or self.state.scene, "note", text=text)

    # ── items and locations ─────────────────────────────────────────────────
    def add_item(self, item: Item, location: dict[str, str]) -> Item:
        if item.id in self.state.items or item.id in self.fixed_objects(location.get("scene", "")):
            item = item.copy(id=self.state.new_id(item.id))
        self.state.items[item.id] = item
        self.state.locations[item.id] = dict(location)
        return item

    def move_item(self, item_id: str, location: dict[str, str]) -> None:
        self.state.locations[item_id] = dict(location)

    def remove_item(self, item_id: str) -> None:
        self.state.items.pop(item_id, None)
        self.state.locations.pop(item_id, None)

    def location(self, item_id: str) -> dict[str, str] | None:
        return self.state.locations.get(item_id)

    def items_where(self, **match: str) -> list[Item]:
        return [
            self.state.items[iid]
            for iid, loc in self.state.locations.items()
            if all(loc.get(k) == v for k, v in match.items())
        ]

    def scene_items(self, scene_id: str | None = None) -> list[Item]:
        return self.items_where(scene=scene_id or self.state.scene)

    def char_items(self, char_id: str, slot: str | None = None) -> list[Item]:
        if slot:
            return self.items_where(char=char_id, slot=slot)
        return self.items_where(char=char_id)

    def party_items(self) -> list[Item]:
        ids = {c.id for c in self.state.living()}
        return [self.state.items[i] for i, loc in self.state.locations.items() if loc.get("char") in ids]

    def holder(self, item_id: str) -> Character | None:
        loc = self.location(item_id) or {}
        return self.state.character(loc["char"]) if "char" in loc else None

    @staticmethod
    def slot_cost(item: Item) -> int:
        if item.rules.get("bulky"):
            return 2 * item.quantity
        stack = item.rules.get("stack")
        if stack:
            return math.ceil(item.quantity / stack)
        return item.quantity

    def slots_used(self, char: Character) -> int:
        coins = math.ceil(char.cp / RULES["carry"]["coins_per_slot"]) if char.cp else 0
        return coins + sum(self.slot_cost(i) for i in self.char_items(char.id, "pack"))

    def hands_used(self, char: Character) -> int:
        return sum(2 if i.rules.get("weapon", {}).get("two_handed") else 1 for i in self.char_items(char.id, "hands"))

    def free_hands(self, char: Character) -> int:
        return RULES["carry"]["hands"] - self.hands_used(char)

    def can_carry(self, char: Character, item: Item) -> bool:
        return self.slots_used(char) + self.slot_cost(item) <= RULES["carry"]["slots"]

    def has_rule(self, rule: str, char: Character | None = None) -> Item | None:
        """First item with a rule, held by a character or by anyone in the party."""
        pool = self.char_items(char.id) if char else self.party_items()
        return next((i for i in pool if i.has_rule(rule)), None)

    # ── leader, light and perception ────────────────────────────────────────
    @property
    def leader(self) -> Character:
        char = self.state.character(self.state.leader)
        if char is None or not char.active:
            active = self.state.active()
            if not active:
                return char  # type: ignore[return-value]
            self.state.leader = active[0].id
            self.emit("leader", f"{active[0].name} now leads the party.")
            char = active[0]
        return char

    def scene_light_sources(self, scene_id: str | None = None) -> list[Item]:
        sid = scene_id or self.state.scene
        sources = [o for o in self.fixed_objects(sid).values() if o.gives_light]
        sources += [i for i in self.scene_items(sid) if i.gives_light]
        return sources

    def carried_light_sources(self) -> list[Item]:
        out = []
        for char in self.state.active():
            out += [i for i in self.char_items(char.id, "hands") if i.gives_light]
        return out

    def flame_available(self) -> bool:
        flames = self.carried_light_sources() + self.scene_light_sources()
        return any(not i.rules.get("light", {}).get("no_flame") for i in flames)

    def party_has_light(self) -> bool:
        if self.scene.get("lit"):
            return True
        return bool(self.carried_light_sources() or self.scene_light_sources())

    def mode_for(self, char: Character | None) -> str:
        if self.party_has_light():
            return "light"
        if char is not None and char.infravision:
            return "infravision"
        return "touch"

    @property
    def mode(self) -> str:
        """The leader's perception mode: it sets descriptions and pace."""
        return self.mode_for(self.leader)

    def time_multiplier(self) -> int:
        return RULES["vision"][self.mode]["time_multiplier"]

    # ── hidden things ───────────────────────────────────────────────────────
    def is_hidden(self, thing_id: str, hidden: dict | None) -> bool:
        return bool(hidden) and thing_id not in self.state.discovered

    def discover(self, thing_id: str) -> None:
        if thing_id not in self.state.discovered:
            self.state.discovered.append(thing_id)

    def visible_objects(self, scene_id: str | None = None) -> list[Item]:
        sid = scene_id or self.state.scene
        objs = [o for o in self.fixed_objects(sid).values() if not self.is_hidden(o.id, o.hidden)]
        return objs + [i for i in self.scene_items(sid) if not self.is_hidden(i.id, i.hidden)]

    # ── transitions ─────────────────────────────────────────────────────────
    def barrier(self, transition: dict) -> Item | None:
        bid = transition.get("barrier")
        if not bid:
            return None
        sid = self.adventure.barrier_scene(bid)
        return self.fixed_objects(sid).get(bid) if sid else None

    def barrier_owner(self, transition: dict) -> str | None:
        return self.adventure.barrier_scene(transition["barrier"]) if transition.get("barrier") else None

    def exits(self, scene_id: str | None = None) -> list[dict[str, Any]]:
        """Exits the party can perceive and travel through, in this scene."""
        sid = scene_id or self.state.scene
        mode = self.mode
        out = []
        for t in self.adventure.transitions.values():
            if t["from"] == sid:
                dest = t["to"]
            elif t["to"] == sid and not t.get("one_way"):
                dest = t["from"]
            else:
                continue
            if self.is_hidden(t["id"], t.get("hidden")):
                continue
            end = (t.get("ends") or {}).get(sid, {})
            barrier = self.barrier(t)
            passable, reason = self.passable(t)
            out.append({
                "id": t["id"],
                "to": dest,
                "label": label_text(end.get("label"), mode) or "a way out",
                "description": text_for(end.get("description"), mode),
                "barrier": barrier.id if barrier else None,
                "barrier_state": self.barrier_state(barrier) if barrier else None,
                "passable": passable,
                "reason": reason,
                "visited": dest in self.state.visited,
            })
        return out

    @staticmethod
    def barrier_state(barrier: Item) -> str:
        if barrier.burning:
            return "burning"
        if barrier.broken or barrier.state.get("fire") == "burnt":
            return "broken"
        if barrier.state.get("locked", "locked" in barrier.rules):
            return "locked"
        return "open" if barrier.state.get("open") else "closed"

    def passable(self, transition: dict) -> tuple[bool, str]:
        barrier = self.barrier(transition)
        if barrier is None:
            return True, ""
        state = self.barrier_state(barrier)
        if state == "burning":
            return False, f"the {barrier.label(self.mode)} is burning"
        if state == "locked":
            key = barrier.rules.get("locked", {}).get("key")
            if key and any(i.id == key or i.id.startswith(key + "-") for i in self.party_items()):
                return True, "unlock"
            return False, f"the {barrier.label(self.mode)} is locked"
        return True, ""

    # ── groups of creatures ─────────────────────────────────────────────────
    def groups_in(self, scene_id: str | None = None) -> list[dict[str, Any]]:
        sid = scene_id or self.state.scene
        return [
            g for g in self.state.groups.values()
            if g["scene"] == sid and any(m["status"] == "ok" for m in g["members"])
        ]

    def spawn_group(self, group_id: str, scene_id: str, attitude: str | None = None) -> dict[str, Any]:
        spec = self.adventure.groups[group_id]
        instance_id = self.state.new_id(group_id)
        members = []
        for m in spec.get("members", []):
            creature = self.adventure.creatures[m["creature"]]
            for n in range(m.get("count", 1)):
                hp = creature["hp"]
                name = m.get("name") or creature.get("name", m["creature"])
                if m.get("count", 1) > 1:
                    name = f"{name} {n + 1}"
                members.append({
                    "id": self.state.new_id(m["creature"]),
                    "creature": m["creature"],
                    "name": name,
                    "hp": hp,
                    "max_hp": hp,
                    "status": "ok",
                    "chief": bool(m.get("chief")),
                })
        group = {
            "id": instance_id,
            "group": group_id,
            "name": spec.get("name", group_id),
            "scene": scene_id,
            "attitude": attitude or spec.get("attitude", "hostile"),
            "members": members,
            "morale_successes": 0,
            "fearless": False,
            "fired": [],
        }
        self.state.groups[instance_id] = group
        return group

    def ensure_scene_groups(self, scene_id: str) -> None:
        """Place a scene's fixed groups the first time the party enters."""
        flag = f"_groups_placed:{scene_id}"
        if self.state.flags.get(flag):
            return
        self.state.flags[flag] = True
        for g in self.adventure.scenes[scene_id].get("groups", []):
            self.spawn_group(g["group"], scene_id, g.get("attitude"))

    def creature(self, member: dict) -> dict:
        return self.adventure.creatures[member["creature"]]

    def group_text(self, group: dict, mode: str) -> str:
        spec = self.adventure.groups[group["group"]]
        text = text_for(spec.get("description"), mode)
        alive = [m for m in group["members"] if m["status"] == "ok"]
        if text:
            return text
        if mode == "touch":
            return "Something moves nearby."
        return ", ".join(m["name"] for m in alive)

    # ── characters ──────────────────────────────────────────────────────────
    def find_character(self, name: str) -> Character | None:
        name = name.lower().strip()
        chars = self.state.living()
        return (next((c for c in chars if c.name.lower() == name or c.id == name), None)
                or next((c for c in chars if c.name.lower().startswith(name)), None))

    def armor_check_penalty(self, char: Character) -> int:
        return sum(i.rules["armor"].get("check_penalty", 0)
                   for i in self.char_items(char.id) if "armor" in i.rules
                   and self.location(i.id).get("slot") in ("worn", "hands"))

    def ac(self, char: Character) -> int:
        armor = sum(i.rules["armor"].get("ac", 0) for i in self.char_items(char.id)
                    if "armor" in i.rules and self.location(i.id).get("slot") in ("worn", "hands"))
        return 10 + char.mod("Agility") + armor + char.augur_bonus("ac") + char.condition_modifier("ac", self.now)

    def inventory_view(self, char: Character) -> dict[str, Any]:
        """A character's actual belongings: equipment slots, pack and free space."""
        def entry(item: Item) -> dict[str, Any]:
            out: dict[str, Any] = {"id": item.id, "name": item.label(), "quantity": item.quantity,
                                   "slots": self.slot_cost(item)}
            if item.state.get("lit"):
                out["lit"] = True
                out["light"] = light_stage(item.state.get("remaining", 0))
            if item.broken:
                out["broken"] = True
            if item.state.get("patched"):
                out["patched"] = True
            if "weapon" in item.rules:
                out["damage"] = item.rules["weapon"].get("damage")
            if "armor" in item.rules:
                out["ac"] = item.rules["armor"].get("ac", 0)
            return out

        hands: list[dict[str, Any] | None] = []
        for item in self.char_items(char.id, "hands"):
            hands.append(entry(item))
            if item.rules.get("weapon", {}).get("two_handed"):
                hands.append({"name": f"({item.label()}, two-handed)", "same_as": item.id})
        hands += [None] * (RULES["carry"]["hands"] - len(hands))
        worn: dict[str, dict[str, Any] | None] = {"body": None, "head": None}
        for item in self.char_items(char.id, "worn"):
            worn[item.rules.get("armor", {}).get("slot", "body")] = entry(item)
        coin_slots = math.ceil(char.cp / RULES["carry"]["coins_per_slot"]) if char.cp else 0
        used = self.slots_used(char)
        return {
            "id": char.id,
            "name": char.name,
            "leader": char.id == self.state.leader,
            "status": char.status,
            "equipment": {"hands": hands, **worn},
            "pack": [entry(i) for i in self.char_items(char.id, "pack")],
            "coins": {"cp": char.cp, "slots": coin_slots},
            "slots": {"used": used, "total": RULES["carry"]["slots"],
                      "free": RULES["carry"]["slots"] - used},
            "free_hands": self.free_hands(char),
            "ac": self.ac(char),
        }

    def weapon_of(self, char: Character) -> Item | None:
        return next((i for i in self.char_items(char.id, "hands") if "weapon" in i.rules), None)

    def fumble_die(self, char: Character) -> str:
        body = next((i for i in self.char_items(char.id, "worn")
                     if i.rules.get("armor", {}).get("slot") == "body"), None)
        return body.rules["armor"].get("fumble", "d4") if body else "d4"

    def drop_held(self, char: Character) -> list[Item]:
        dropped = self.char_items(char.id, "hands")
        for item in dropped:
            self.move_item(item.id, {"scene": self.state.scene})
        return dropped

    def fall(self, char: Character) -> None:
        """A character at 0 HP appears dead (docs/design.md 9.3)."""
        char.hp = 0
        char.status = "fallen"
        char.fallen_at = self.now
        dropped = self.drop_held(char)
        text = f"{char.name} falls and lies still."
        if any(i.gives_light for i in dropped):
            text += " Their light drops to the floor, still burning."
        self.emit("fall", text, character=char.id)
        self.note(f"{char.name} fell here.")

    def kill(self, char: Character, reason: str) -> None:
        char.status = "dead"
        char.hp = 0
        for item in self.char_items(char.id):
            self.move_item(item.id, {"scene": self.state.scene})
        self.emit("death", f"{char.name} is dead. {reason}".strip(), character=char.id)
        self.note(f"{char.name} died here.")

    # ── time ────────────────────────────────────────────────────────────────
    def advance(self, minutes: int, travel: bool = False) -> None:
        """Advance the game clock: burn lights, run timers, expire conditions.

        Travel between the village and an adventure burns no torch time (design 13).
        """
        if minutes <= 0:
            return
        was_lit = self.party_has_light()
        self.state.clock += minutes
        for item in ([] if travel else list(self.state.items.values())):
            if "light" in item.rules and item.state.get("lit"):
                item.state["remaining"] = item.state.get("remaining", item.rules["light"]["minutes"]) - minutes
                if item.state["remaining"] <= 0:
                    self._light_out(item)
        for timer in sorted(list(self.state.timers), key=lambda t: t["due"]):
            if timer["due"] <= self.now:
                self.state.timers.remove(timer)
                self.run_effects(timer["effects"], None, timer.get("scene"), timer.get("self"))
        for char in self.state.characters:
            char.conditions = [c for c in char.conditions if c.get("until") is None or c["until"] > self.now]
            if char.status == "fallen" and char.fallen_at is not None and \
                    self.now - char.fallen_at > RECOVER_BODY_WINDOW_MINUTES:
                self.kill(char, "No one reached the body in time.")
        self.check_deadline()
        if was_lit and not self.party_has_light() and not travel:
            self.on_darkness()

    def _light_out(self, item: Item) -> None:
        holder = self.holder(item.id)
        where = f"{holder.name}'s " if holder else "The "
        if item.rules["light"].get("refill"):
            item.state["lit"] = False
            item.state["remaining"] = 0
            self.emit("light", f"{where}{item.label()} runs dry and goes dark.")
        elif item.quantity > 1:
            item.quantity -= 1
            item.state["lit"] = False
            item.state["remaining"] = item.rules["light"]["minutes"]
            self.emit("light", f"{where}{item.label()} burns out.")
        else:
            self.remove_item(item.id)
            self.emit("light", f"{where}{item.label()} burns out.")

    def on_darkness(self) -> None:
        self.emit("darkness", "Darkness closes in.")
        leader = self.leader
        if leader and not leader.infravision:
            seers = [c for c in self.state.active() if c.infravision]
            if seers:
                self.emit("advice", f"{leader.name} cannot see in the dark. {seers[0].name} could lead "
                                    f"(type: leader {seers[0].name}).")

    def check_deadline(self) -> None:
        at = self.deadline_at()
        if at is not None and not self.state.deadline_fired and self.now >= at:
            self.state.deadline_fired = True
            self.state.flags["deadline_passed"] = True
            deadline = self.adventure.data.get("deadline")
            text = deadline.get("text") if isinstance(deadline, dict) else self.adventure.data.get("deadline_text")
            self.emit("deadline", text or "The deadline has passed.")

    def schedule(self, delay: int, effects: list[dict], scene_id: str | None = None, self_id: str | None = None) -> None:
        self.state.timers.append({"due": self.now + delay, "effects": effects, "scene": scene_id, "self": self_id})

    def light_status(self) -> list[str]:
        out = []
        for char in self.state.active():
            for item in self.char_items(char.id, "hands"):
                if item.gives_light:
                    out.append(f"{char.name}'s {item.label()} is {light_stage(item.state.get('remaining', 0))}")
        return out

    # ── effects (adventure data) ────────────────────────────────────────────
    def run_effects(self, effects: list[dict], actor: Character | None,
                    scene_id: str | None = None, self_id: str | None = None) -> None:
        sid = scene_id or self.state.scene
        for effect in effects:
            if not self._condition_met(effect.get("when"), sid):
                continue
            self._run_effect(effect, actor, sid, self_id)

    def _condition_met(self, when: dict | None, sid: str) -> bool:
        if not when:
            return True
        if "flag" in when and self.state.flags.get(when["flag"]) != when.get("equals", True):
            return False
        if "state" in when:
            target, key, value = when["state"]
            obj = self.fixed_objects(sid).get(target) or self.state.items.get(target)
            if obj is None or obj.state.get(key) != value:
                return False
        return True

    def set_object_state(self, sid: str, target: str, key: str, value: Any) -> None:
        if target in self.fixed_objects(sid):
            self.change(sid, "set_state", target=target, key=key, value=value)
        elif target in self.state.items:
            self.state.items[target].state[key] = value
        else:
            owner = self.adventure.barrier_scene(target)
            if owner:
                self.change(owner, "set_state", target=target, key=key, value=value)

    def _run_effect(self, effect: dict, actor: Character | None, sid: str, self_id: str | None) -> None:
        op = effect["op"]
        target = effect.get("target", self_id)
        if target == "self":
            target = self_id
        if op == "message":
            self.emit("message", text_for(effect["text"], self.mode) or "")
        elif op == "set_state":
            self.set_object_state(sid, target, effect["key"], effect["value"])
        elif op == "set_description":
            if target in self.fixed_objects(sid):
                self.change(sid, "set_description", target=target, description=effect["description"])
            elif target in self.state.items:
                self.state.items[target].state["description"] = effect["description"]
        elif op == "set_flag":
            self.state.flags[effect["flag"]] = effect.get("value", True)
        elif op == "reveal":
            self.discover(target)
        elif op == "damage":
            self._effect_damage(effect, actor)
        elif op == "douse":
            self.douse_party()
        elif op == "soak":
            self.soak_party(effect.get("minutes", RULES["soak_minutes"]))
        elif op == "give_item":
            item = parse_item(effect["item"])
            if actor:
                self.add_item(item, {"char": actor.id, "slot": "pack"})
        elif op == "add_item":
            self.add_item(parse_item(effect["item"]), {"scene": effect.get("scene", sid)})
        elif op == "remove":
            if target in self.state.items:
                self.remove_item(target)
            else:
                self.change(sid, "remove", target=target)
        elif op == "loud":
            self.state.flags["_loud"] = True
        elif op == "start_combat":
            self.state.flags["_start_combat"] = effect.get("group")

    def _effect_damage(self, effect: dict, actor: Character | None) -> None:
        from engine import rules  # avoid an import cycle
        who = effect.get("who", "actor")
        targets = self.state.active() if who in ("party", "each") else ([actor] if actor else [])
        for char in targets:
            avoid = effect.get("save") or effect.get("check")
            if avoid:
                if "save" in effect:
                    result = rules.saving_throw(self, char, effect["save"]["type"], effect["save"]["dc"])
                else:
                    result = rules.ability_check(self, char, avoid["ability"], avoid["dc"],
                                                 occupation_applies=avoid.get("occupation_applies", True))
                if result["success"]:
                    self.emit("avoid", f"{char.name} avoids harm ({result['text']}).")
                    continue
            amount = self.dice.roll(effect["dice"]).total
            self.hurt(char, amount, effect.get("text", "harm"))

    def hurt(self, char: Character, amount: int, source: str = "", announce: bool = True) -> None:
        char.hp -= amount
        if announce:
            self.emit("damage", f"{char.name} takes {amount} damage{(' from ' + source) if source else ''}.",
                      character=char.id, amount=amount)
        if char.hp <= 0 and char.status == "ok":
            self.fall(char)

    def douse_party(self) -> None:
        for item in self.party_items() + self.scene_items():
            if item.state.get("lit") and not item.rules.get("light", {}).get("no_flame"):
                item.state["lit"] = False
                self.emit("light", f"The {item.label()} is put out.")

    def soak_party(self, minutes: int) -> None:
        self.douse_party()
        for item in list(self.party_items()):
            loc = self.location(item.id) or {}
            container = self.state.items.get(loc.get("in", ""))
            if container and container.has_rule("waterproof"):
                continue
            if material(item.material).get("water") == "ruined":
                self.remove_item(item.id)
                self.emit("ruined", f"The {item.label()} is ruined by the water.")
            elif "light" in item.rules:
                item.state["soaked_until"] = self.now + minutes
        self.emit("soaked", "Everything you carry is soaked.")

    # ── views ───────────────────────────────────────────────────────────────
    def scene_view(self) -> dict[str, Any]:
        """What the party perceives here, for the Judge and the player."""
        return self.fill(self._scene_view())

    def _scene_view(self) -> dict[str, Any]:
        mode = self.mode
        sid = self.state.scene
        objects = []
        for obj in self.visible_objects(sid):
            entry = {"id": obj.id, "name": obj.label(mode), "description": obj.describe(mode)}
            state = {k: v for k, v in obj.state.items() if k in ("integrity", "fire", "open", "locked", "lit", "oiled")}
            if state:
                entry["state"] = state
            if obj.notes and mode == "light":
                entry["judge_notes"] = obj.notes
            entry["portable"] = obj.portable
            objects.append(entry)
        return {
            "scene": sid,
            "name": label_text(self.scene.get("name"), mode),
            "perception": mode,
            "description": text_for(self.scene.get("description"), mode),
            "objects": objects,
            "exits": self.exits(sid),
            "creatures": [
                {"group": g["id"], "attitude": g["attitude"], "text": self.group_text(g, mode),
                 "members": [{"id": m["id"], "name": m["name"] if mode != "touch" else "something",
                              "status": m["status"]} for m in g["members"] if m["status"] == "ok"]}
                for g in self.groups_in(sid)
            ],
            "history": self.history(sid)[-8:],
            "lit": self.party_has_light(),
            **({"shop": self.shop_view()} if self.scene.get("shop") else {}),
            **({"available_actions": self.available_actions()} if self.scene.get("menu") else {}),
        }

    def purse_view(self) -> dict[str, Any]:
        """Each character's remaining money, and the party's total, which purchases may draw on."""
        chars = self.state.living()
        party = sum(c.cp for c in chars)
        return {"characters": [{"name": c.name, "leader": c.id == self.state.leader, "cp": c.cp,
                                "text": money_text(c.cp)} for c in chars],
                "party_cp": party, "party_text": money_text(party)}

    def shop_view(self) -> dict[str, Any]:
        """What the shop here sells, with prices in copper pieces."""
        from engine.catalog import make_item
        shop = self.scene["shop"]
        prices = {name: make_item(name).cost_cp for name in shop.get("stock", [])}
        for custom in shop.get("custom", []):
            name = custom["name"]["light"] if isinstance(custom["name"], dict) else custom["name"]
            prices[name] = custom.get("cost_cp", 0)
        return {"sells": prices, "buys": "anything ordinary, at half its cost (haggling can change that)",
                "purse": self.purse_view()}

    def render_scene(self, view: dict[str, Any] | None = None) -> str:
        view = view or self.scene_view()
        lines = []
        if view.get("name"):
            lines.append(view["name"].upper())
        if view.get("description"):
            lines.append(view["description"])
        notable = [o for o in view["objects"] if o.get("description")]
        for obj in notable:
            lines.append(obj["description"])
        for c in view["creatures"]:
            lines.append(c["text"])
        exits = [e["label"] for e in view["exits"]]
        if exits:
            lines.append("Ways on: " + "; ".join(exits) + ".")
        if view.get("available_actions"):
            lines.append("You can: " + "; ".join(a["label"] for a in view["available_actions"]) + ".")
        if view.get("shop"):
            purse = view["shop"]["purse"]
            lines.append("Money: " + "; ".join(f"{c['name']} {c['text']}" for c in purse["characters"])
                         + f" (party total {purse['party_text']}).")
            lines.append("A trader here sells: " + ", ".join(f"{k} ({v} cp)" for k, v in view["shop"]["sells"].items()) + ".")
        if view["history"]:
            lines.append("Earlier here: " + " ".join(view["history"][-3:]))
        return "\n".join(lines)

