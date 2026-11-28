"""
Game: the engine's entry point, used by the MCP server.

Each request runs as a transaction: if anything unexpected fails, the state is
restored and nothing is saved (design 12.2). The game autosaves after every
action to a single slot per adventure (design 12.3).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from engine import combat
from engine.actions import ActionError, Actions, NeedsConfirmation, clock_text, validate_proposal
from engine.adventure import Adventure, AdventureError, load_adventure, resolve_adventures_dir, scan_adventures
from engine.character import generate_character
from engine.dice import Dice
from engine.encounters import apply_level_events
from engine.parser import parse
from engine.state import DATA_DIR, GameState, SaveStore
from engine.world import World
from rulesets.dcc import ALIGNEMENTS, GENDERS, load_table
from rulesets.game import RULES

LOGS_DIR = DATA_DIR / "logs"
HISTORY_KEPT = 20
RECENT_FOR_JUDGE = 6


class Game:
    def __init__(self, adventure: Adventure, state: GameState, dice: Dice | None = None,
                 store: SaveStore | None = None, log_dir: Path | None = LOGS_DIR,
                 level_service: Callable[[int, int, list[str]], int] = apply_level_events):
        self.adventure = adventure
        self.state = state
        self.dice = dice or Dice()
        self.store = store or SaveStore()
        self.log_dir = log_dir
        self.level_service = level_service

    # ── creation ────────────────────────────────────────────────────────────
    @classmethod
    def new(cls, source: str | None = None, seed: int | None = None, party_size: int = 4,
            adventures_dir: str | None = None, **kwargs) -> tuple["Game", dict]:
        """Start a game in the village tavern.

        The adventure is picked at random among the funnels in `adventures_dir`
        (a 0-level party only gets funnel hooks, design 13), unless `source`
        names one: a file path, folder, URL or bundled id.
        """
        dice = Dice(seed)
        if source is None:
            funnels = [a for a in scan_adventures(adventures_dir) if a["ok"] and a["funnel"]]
            if not funnels:
                raise AdventureError(f"No funnel adventure in {resolve_adventures_dir(adventures_dir)}.")
            source = dice.choice(funnels)["path"]
        adventure = load_adventure(source)
        if party_size and not adventure.funnel:
            # Design 13: a 0-level party always gets funnel hooks.
            raise AdventureError(f"'{adventure.title}' is not a funnel. A 0-level party can only begin a funnel "
                                 "(an adventure numbered F...).")
        start_level = adventure.encounters.get("level", RULES["encounter_level"]["default_start"])
        state = GameState(
            adventure_id=adventure.id,
            adventure_source=adventure.source or source,
            scene=adventure.start,
            clock=adventure.data.get("clock_start", 0),
            encounter={"level": start_level, "start": start_level, "carry": 0, "dark": 0, "quiet": 0},
        )
        names = load_table("village_names")
        state.village = {"name": dice.choice(names["villages"]), "tavern": dice.choice(names["taverns"])}
        game = cls(adventure, state, dice, **kwargs)
        world = game.world()
        for sid, items in adventure.items.items():
            for item in items.values():
                world.add_item(item.copy(), {"scene": sid})
        for n in range(party_size):
            char, items = generate_character(dice, f"c{n + 1}", taken={c.name for c in state.characters})
            char.rank = "front" if n < adventure.scenes[adventure.start].get("front_rank", 2) else "rear"
            state.characters.append(char)
            for item in items:
                slot = "hands" if "weapon" in item.rules and world.free_hands(char) >= (
                    2 if item.rules["weapon"].get("two_handed") else 1) and not world.char_items(char.id, "hands") else "pack"
                world.add_item(item, {"char": char.id, "slot": slot})
        state.leader = state.characters[0].id
        Actions(world, level_service=game.level_service).enter_scene()
        result = game._finish(world, "new game", None, [])
        return game, result

    @classmethod
    def load(cls, **kwargs) -> "Game":
        """Resume the saved game, reloading its adventure from where it came from."""
        store = kwargs.pop("store", None) or SaveStore()
        state = store.load()
        return cls(load_adventure(state.adventure_source), state, store=store, **kwargs)

    def world(self) -> World:
        return World(self.adventure, self.state, self.dice)

    # ── requests ────────────────────────────────────────────────────────────
    def command(self, text: str) -> dict[str, Any]:
        """A player command. Handled here if the built-in parser understands it."""
        text = text.strip()
        if self.state.pending:
            pending = self.state.pending
            self.state.pending = None
            if text.lower() in ("y", "yes", "confirm", "do it"):
                pending["proposal"]["actions"][0]["confirm"] = True
                return self.act(pending["proposal"], source="confirmation", text=text)
            world = self.world()
            world.emit("cancel", "You think better of it.")
            return self._finish(world, text, None, [])
        if self.state.phase == "over":
            return self._result(self.world(), [], handled=True, extra_summary="The adventure is over.")
        proposal = parse(text, self.world())
        if proposal is None:
            leader = self.state.character(self.state.leader)
            return {"handled": False, "reason": "The built-in parser did not understand this; the Judge must interpret it.",
                    "leader": leader.name if leader else None, "context": self.context()}
        return self.act(proposal, source="parser", text=text)

    def act(self, proposal: dict | str, source: str = "judge", text: str = "") -> dict[str, Any]:
        """Validate and resolve a proposal (from the parser or the Judge)."""
        if isinstance(proposal, str):
            try:
                proposal = json.loads(proposal)
            except json.JSONDecodeError as exc:
                return {"ok": False, "handled": True, "errors": [f"Proposal is not valid JSON: {exc}"]}
        errors = validate_proposal(proposal)
        if errors:
            result = {"ok": False, "handled": True, "errors": errors, "events": [], "summary": "\n".join(errors)}
            self._log(source, text, proposal, result)
            return result
        if self.state.phase == "over":
            return {"ok": False, "handled": True, "errors": ["The adventure is over."]}
        if proposal.get("clarify"):
            return {"ok": True, "handled": True, "clarify": proposal["clarify"], "events": [],
                    "summary": proposal["clarify"]}
        snapshot = self.state.clone()
        world = self.world()
        actions = Actions(world, level_service=self.level_service)
        errors = []
        confirmation = None
        try:
            actions.run(proposal)
        except ActionError as exc:
            errors.append(str(exc))
        except NeedsConfirmation as exc:
            confirmation = exc.message
            # earlier actions in this proposal stay done; resume from the one needing confirmation
            self.state.pending = {"proposal": {"actions": proposal["actions"][exc.index:]}, "message": exc.message}
            world.emit("confirm", exc.message + " (yes/no)")
        except Exception:
            self.state = snapshot
            raise
        self._check_goal(world)
        return self._finish(world, text or json.dumps(proposal), proposal, errors, source, confirmation)

    # ── goal and ending ─────────────────────────────────────────────────────
    def _check_goal(self, world: World) -> None:
        goal = self.adventure.data.get("goal")
        if not goal or self.state.phase == "over" or not world.in_village:
            return
        carried = {i.id.split("-")[0] for i in world.party_items()} | {i.id for i in world.party_items()}
        have = [g for g in goal.get("items", []) if g in carried]
        if len(have) >= goal.get("need", 1) and self.state.active():
            self.state.phase = "over"
            self.state.outcome = "won"
            for char in self.state.active():
                char.ready_to_level_up = True
            world.emit("victory", goal.get("text", "You have done what you came to do."))
            world.emit("ending", "Survivors are marked ready to level up: "
                       + ", ".join(c.name for c in self.state.active()) + ".")

    # ── results ─────────────────────────────────────────────────────────────
    def _finish(self, world: World, text: str, proposal: dict | None, errors: list[str],
                source: str = "engine", confirmation: str | None = None) -> dict[str, Any]:
        self.state.turn += 1
        result = self._result(world, errors, handled=True, confirmation=confirmation)
        self.state.history.append({"player": text, "result": result["summary"][:600]})
        self.state.history = self.state.history[-HISTORY_KEPT:]
        self.store.save(self.state)
        self._log(source, text, proposal, result)
        return result

    def _result(self, world: World, errors: list[str], handled: bool, confirmation: str | None = None,
                extra_summary: str = "") -> dict[str, Any]:
        lines = [e["text"] for e in world.events if e.get("text")]
        if errors:
            lines += errors
        if extra_summary:
            lines.append(extra_summary)
        leader = self.state.character(self.state.leader)
        return {
            "ok": not errors,
            "handled": handled,
            "leader": leader.name if leader else None,
            "available_actions": world.available_actions() if self.state.phase != "over" else [],
            "events": world.events,
            "errors": errors,
            "summary": "\n".join(lines),
            "perception": world.mode if self.state.active() else "none",
            "phase": self.state.phase,
            "game_over": self.state.phase == "over",
            "outcome": self.state.outcome,
            "needs_confirmation": confirmation,
        }

    def _log(self, source: str, text: str, proposal: dict | None, result: dict) -> None:
        if not self.log_dir:
            return
        self.log_dir.mkdir(parents=True, exist_ok=True)
        entry = {"time": time.time(), "turn": self.state.turn, "clock": self.state.clock, "source": source,
                 "input": text, "proposal": proposal, "errors": result["errors"],
                 "events": [{"kind": e["kind"], "text": e["text"]} for e in result["events"]]}
        with open(self.log_dir / f"{self.adventure.id}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # ── the Judge's view ────────────────────────────────────────────────────
    def context(self) -> dict[str, Any]:
        """Everything the Judge may know right now: only what the party perceives."""
        world = self.world()
        party = []
        for c in self.state.characters:
            def items(slot):
                return [{"id": i.id, "name": i.label(), "quantity": i.quantity,
                         **({"lit": True} if i.state.get("lit") else {}),
                         **({"broken": True} if i.broken else {})} for i in world.char_items(c.id, slot)]
            party.append({
                "id": c.id, "name": c.name, "race": c.race, "gender": c.gender, "alignment": c.alignment,
                "occupation": c.occupation, "trained_weapon": c.trained_weapon, "hp": c.hp, "max_hp": c.max_hp,
                "ac": world.ac(c), "status": c.status, "rank": c.rank, "leader": c.id == self.state.leader,
                "infravision": c.infravision, "abilities": c.abilities, "cp": c.cp,
                "hands": items("hands"), "worn": items("worn"), "pack": items("pack"),
            })
        context = {
            "adventure": self.adventure.title,
            "village": self.state.village,
            "available_actions": world.available_actions(),
            "phase": self.state.phase,
            "outcome": self.state.outcome,
            "clock": clock_text(self.state.clock),
            "scene": world.scene_view(),
            "party": party,
            "light": world.light_status(),
            "recent": self.state.history[-RECENT_FOR_JUDGE:],
            "facts": self.state.facts,
            "pending_confirmation": (self.state.pending or {}).get("message"),
        }
        deadline = world.deadline_at()
        if deadline is not None:
            context["time_left"] = f"about {max(0, deadline - self.state.clock) // 60} hours"
        if self.state.combat:
            context["combat"] = {
                "round": self.state.combat["round"],
                "enemies": [{"id": m["id"], "name": m["name"] if world.mode != "touch" else "something",
                             "wounded": m["hp"] < m["max_hp"]} for _, m in combat.enemies(world)],
                "orders": self.state.combat["orders"],
            }
        return context

    def inventory(self, character: str | None = None) -> dict[str, Any]:
        """The party's actual belongings, or one character's. No game time passes."""
        world = self.world()
        if character:
            char = world.find_character(character)
            if char is None:
                return {"ok": False, "errors": [f"No character '{character}'."]}
            chars = [char]
        else:
            chars = self.state.living()
        return {"ok": True, "display_only": True, "inventory": [world.inventory_view(c) for c in chars]}

    # ── party set-up ────────────────────────────────────────────────────────
    def customize(self, character: str, name: str | None = None, gender: str | None = None,
                  alignment: str | None = None) -> dict[str, Any]:
        """Rename a character or set gender and alignment. No game time passes."""
        world = self.world()
        char = world.find_character(character)
        if char is None:
            return {"ok": False, "errors": [f"No character '{character}'."]}
        if gender and gender not in GENDERS:
            return {"ok": False, "errors": [f"Gender must be one of {GENDERS}."]}
        if alignment and alignment not in ALIGNEMENTS:
            return {"ok": False, "errors": [f"Alignment must be one of {ALIGNEMENTS}."]}
        char.name = name or char.name
        char.gender = gender or char.gender
        char.alignment = alignment or char.alignment
        self.store.save(self.state)
        return {"ok": True, "character": char.to_dict()}
