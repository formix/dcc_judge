"""
Built-in command parser (design 3.2: simple commands go straight to the engine).

It turns plain commands into a proposal, the same structure a Judge model
returns. It returns None for anything it does not understand; the Judge then
interprets it.
"""

from __future__ import annotations

import re

from engine.actions import _norm

ARTICLES = r"(?:the |a |an |my |some )?"

SIMPLE: list[tuple[str, str]] = [
    (r"^(?:l|look|look around)$", "look"),
    (r"^(?:i|inv|inventory)$", "inventory"),
    (r"^(?:status|party|stats|sheet)$", "status"),
    (r"^(?:wait|rest|wait a while)$", "wait"),
    (r"^(?:defend|guard|parry|hold)$", "defend"),
    (r"^(?:search|search around|search the room|search here)$", "search"),
    (r"^(?:fight on|continue|next round|keep fighting)$", "defend_keep"),
]

PATTERNS: list[tuple[str, str, tuple[str, ...]]] = [
    (r"^(?:look at|examine|x|inspect|check|read) (.+)$", "examine", ("target",)),
    (r"^(?:inventory|inv|i) (?:of )?(.+)$", "inventory_of", ("actor",)),
    (r"^(?:make )?(.+?) (?:the )?leader$", "leader", ("target",)),
    (r"^(?:leader|lead) (.+)$", "leader", ("target",)),
    (r"^(.+?) (?:leads|takes the lead)$", "leader", ("target",)),
    (r"^(?:sneak|creep|tiptoe|quietly go|quietly move|sneak through|sneak to|sneak into|sneak down|sneak up|move quietly to|move quietly through) (.+)$", "move_silent", ("target",)),
    (r"^(?:go|walk|move|enter|climb|head|descend|ascend|take the|go through|go down|go up|go into|go to|crawl|crawl into|crawl through|slide down|ride|jump into) (.+)$", "move", ("target",)),
    (r"^(?:search|search the|search in|look in|look behind|look under) (.+)$", "search", ("target",)),
    (r"^(?:take|get|grab|pick up|pick) (.+)$", "take", ("target",)),
    (r"^(?:drop|leave|put down) (.+)$", "drop", ("target",)),
    (r"^(?:give|hand|pass) (.+?) to (.+)$", "give", ("target", "to")),
    (r"^(?:equip|wield|wear|ready|draw|hold|put on) (.+)$", "equip", ("target",)),
    (r"^(?:unequip|remove|stow|put away|sheathe|take off) (.+)$", "unequip", ("target",)),
    (r"^(?:light|ignite) (.+)$", "light", ("target",)),
    (r"^(?:light)$", "light", ()),
    (r"^(?:extinguish|douse|snuff|put out) (.+)$", "extinguish", ("target",)),
    (r"^(?:fill|refill) (.+)$", "fill", ("target",)),
    (r"^(?:force|bash|kick|kick open|force open|shoulder) (.+)$", "force", ("target",)),
    (r"^(?:break|smash|destroy|shatter) (.+?)(?: with (.+))?$", "break", ("target", "item")),
    (r"^(?:pick the lock (?:of|on)|pick lock|pick the lock|unlock) (.+?)(?: with .+)?$", "pick_lock", ("target",)),
    (r"^(?:burn|set fire to|torch) (.+)$", "burn", ("target",)),
    (r"^set (.+) on fire$", "burn", ("target",)),
    (r"^(?:repair|fix|patch|mend) (.+)$", "repair", ("target",)),
    (r"^(?:front|to the front|front rank) ?(.*)$", "rank_front", ("actor",)),
    (r"^(?:rear|back|to the rear|rear rank) ?(.*)$", "rank_rear", ("actor",)),
    (r"^(.+?) (?:to|goes to|moves to) the (front|rear)(?: rank)?$", "rank", ("actor", "rank")),
    (r"^(?:all|everyone|everybody) (?:attack|hit|strike|fight|kill) ?(.*)$", "attack_all", ("target",)),
    (r"^(?:attack|hit|strike|kill|fight|stab|shoot|charge) (.+)$", "attack", ("target",)),
    (r"^(?:attack|fight)$", "attack", ()),
    (r"^(?:flee|run|retreat|escape|run away)(?: to| through| by| down| into)? ?(.*)$", "flee", ("target",)),
    (r"^(?:say|shout|whisper|tell \w+) ['\"]?(.+?)['\"]?$", "talk", ("text",)),
    (r"^use (.+?) on (.+)$", "use_on", ("item", "target")),
    (r"^(?:buy|purchase) (\d+) (.+)$", "buy_n", ("quantity", "target")),
    (r"^(?:buy|purchase) (.+)$", "buy", ("target",)),
    (r"^(?:haggle over|haggle|negotiate|bargain) (.+)$", "sell_haggle", ("target",)),
    (r"^sell (.+)$", "sell", ("target",)),
    (r"^(?:heal|bandage|bind|tend|dress) (.+?)(?:'s wounds| wounds)?$", "heal", ("target",)),
]

COVER = re.compile(r"^(.+?) (?:under cover of|in time with|with the rhythm of|timing (?:my |our )?steps (?:to|with)) (.+)$")


def _split(text: str) -> list[str]:
    parts = re.split(r"\s*(?:;|\bthen\b|\band then\b|\. )\s*", text.strip().rstrip("."))
    return [p for p in parts if p]


def parse(text: str, world) -> dict | None:
    actions = []
    for part in _split(text.lower()):
        action = _parse_one(part, world)
        if action is None:
            return None
        actions.append(action)
    return {"actions": actions} if actions else None


def _strip_actor(part: str, world) -> tuple[str | None, str]:
    m = re.match(r"^(\w+)[,:]\s*(.+)$", part)
    if m and world.find_character(m.group(1)):
        return world.find_character(m.group(1)).name, m.group(2)
    words = part.split(" ", 1)
    if len(words) == 2 and any(c.name.lower() == words[0] for c in world.state.living()):
        rest = words[1]
        if not re.match(r"^(?:leads|takes the lead|to the|goes to|moves to)", rest):
            return world.find_character(words[0]).name, rest
    return None, part


def _parse_one(part: str, world) -> dict | None:
    actor, cmd = _strip_actor(part, world)
    cmd = cmd.strip()
    action = None
    for pattern, kind in SIMPLE:
        if re.match(pattern, cmd):
            action = {"type": "defend" if kind == "defend_keep" else kind}
            if kind == "defend_keep":
                action = {"type": "wait"} if world.state.phase != "combat" else {"type": "defend", "keep": True}
            break
    if action is None:
        cover = None
        m = COVER.match(cmd)
        if m:
            cmd, cover = m.group(1), m.group(2)
        for pattern, kind, groups in PATTERNS:
            m = re.match(pattern, cmd)
            if not m:
                continue
            values = {g: (m.group(i + 1) or "").strip() for i, g in enumerate(groups)}
            values = {k: _strip_articles(v) for k, v in values.items() if v}
            action = _build(kind, values, world)
            if action is not None:
                if cover and action["type"] == "move":
                    action["silent"] = True
                    action["cover"] = _strip_articles(cover)
                break
    if action is None:
        action = _interaction(cmd, world)
    if action is None:
        return None
    if actor and "actor" not in action:
        action["actor"] = actor
    return action


def _strip_articles(text: str) -> str:
    return re.sub(rf"^{ARTICLES}", "", text).strip()


def _build(kind: str, v: dict, world) -> dict | None:
    if kind == "move_silent":
        return {"type": "move", "target": v.get("target"), "silent": True}
    if kind == "inventory_of":
        return {"type": "inventory", "actor": v["actor"]} if world.find_character(v["actor"]) else None
    if kind == "leader":
        return {"type": "leader", "target": v["target"]} if world.find_character(v["target"]) else None
    if kind == "rank_front":
        return {"type": "rank", "rank": "front", **({"actor": v["actor"]} if v.get("actor") else {})}
    if kind == "rank_rear":
        return {"type": "rank", "rank": "rear", **({"actor": v["actor"]} if v.get("actor") else {})}
    if kind == "rank":
        return {"type": "rank", "actor": v["actor"], "rank": v["rank"]} if world.find_character(v["actor"]) else None
    if kind == "attack_all":
        return {"type": "attack", "target": v.get("target"), "all": True}
    if kind == "take" and v.get("target", "").startswith("lock"):
        return None
    if kind == "buy_n":
        return {"type": "buy", "target": v["target"], "quantity": int(v["quantity"])}
    if kind == "sell_haggle":
        return {"type": "sell", "target": v["target"], "negotiate": True}
    if kind == "use_on":
        return _use_on(v["item"], v["target"], world)
    if kind == "flee":
        return {"type": "flee", "target": v.get("target") or None}
    out = {"type": kind}
    out.update(v)
    if kind == "search" and _norm(v.get("target", "")) in ("room", "area", "here", "around", "everywhere"):
        out.pop("target")
    return out


def _interaction_candidates(world):
    objs = list(world.visible_objects())
    for ex in world.exits():
        if ex["barrier"]:
            objs.append(world.barrier(world.adventure.transitions[ex["id"]]))
    return [o for o in objs if o.interactions]


def _interaction(cmd: str, world) -> dict | None:
    """'<verb> <object>' for authored interactions (design 5: scene actions)."""
    words = cmd.split(" ", 1)
    if len(words) < 2:
        return None
    verb, rest = words[0], _strip_articles(words[1])
    from engine.actions import resolve_name
    mode = world.mode
    for obj in _interaction_candidates(world):
        for inter in obj.interactions:
            if verb in inter.get("verbs", []) or verb == inter["id"]:
                if resolve_name(rest, [(obj.id, [obj.label(mode), obj.label("light")])]) == obj.id:
                    return {"type": "interact", "target": obj.label(mode), "interaction": inter["id"]}
    return None


def _use_on(item_text: str, target_text: str, world) -> dict | None:
    from engine.actions import resolve_name
    mode = world.mode
    items = world.party_items()
    item_id = resolve_name(item_text, [(i.id, [i.label()]) for i in items])
    if item_id is None:
        return None
    item = world.state.items[item_id]
    for obj in _interaction_candidates(world):
        if resolve_name(target_text, [(obj.id, [obj.label(mode), obj.label("light")])]) != obj.id:
            continue
        for inter in obj.interactions:
            if inter.get("requires_rule") and inter["requires_rule"] in item.rules:
                return {"type": "interact", "target": obj.label(mode), "interaction": inter["id"]}
    return None
