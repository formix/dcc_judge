"""
Adventure data: loading and validation (docs/design.md sections 4 and 14).

An adventure is a YAML file. The original is never modified; play changes
live in the save. Top-level keys:

    id, title           identity
    start               scene the party starts in
    home                scene survivors return to (the village, or the
                        dungeon entrance standing in for it)
    clock_start         game minutes already elapsed at the start
    deadline            optional game minute after which the deadline fires
    deadline_text       message shown when it fires
    encounters          {level, table: [...]} shared wandering table
    creatures           creature statistics by id
    groups              creature groups by id
    scenes              list of scenes
    transitions         list of links between scenes
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from engine.catalog import make_item
from models.item import Item

ADVENTURES_DIR = Path(__file__).resolve().parents[2] / "adventures"

EFFECT_OPS = {
    "message", "set_state", "set_description", "set_flag", "reveal", "damage",
    "douse", "soak", "give_item", "add_item", "remove", "loud", "start_combat",
}
ITEM_KEYS = {"id", "name", "description", "material", "rules", "notes", "portable",
             "quantity", "cost_cp", "state", "hidden", "interactions", "catalog"}
SCENE_KEYS = {"id", "name", "description", "lit", "safe", "encounters", "closed", "entrance",
              "front_rank", "objects", "groups", "traps", "notes", "shop"}
TRANSITION_KEYS = {"id", "from", "to", "one_way", "barrier", "minutes", "ends", "hidden", "on_traverse"}


class AdventureError(ValueError):
    pass


def parse_item(data: dict[str, Any], scene_id: str | None = None) -> Item:
    """Build an Item from adventure data; `catalog:` copies a catalog item."""
    unknown = set(data) - ITEM_KEYS
    if unknown:
        raise AdventureError(f"Object {data.get('id')} in {scene_id}: unknown keys {sorted(unknown)}")
    data = dict(data)
    base_name = data.pop("catalog", None)
    if base_name:
        item = make_item(base_name, data.get("quantity", 1))
        for key, value in data.items():
            if key == "rules":
                item.rules.update(value)
            elif key == "state":
                item.state.update(value)
            else:
                setattr(item, key, value)
        return item
    data.setdefault("portable", False)
    if "name" not in data:
        raise AdventureError(f"Object {data.get('id')} in {scene_id} needs a name")
    return Item.from_dict(data)


@dataclass
class Adventure:
    data: dict[str, Any]
    source: str | None = None          # file path or URL it was loaded from
    scenes: dict[str, dict[str, Any]] = field(default_factory=dict)
    transitions: dict[str, dict[str, Any]] = field(default_factory=dict)
    objects: dict[str, dict[str, Item]] = field(default_factory=dict)  # fixed, by scene
    items: dict[str, dict[str, Item]] = field(default_factory=dict)    # portable, by scene

    def __post_init__(self):
        for scene in self.data.get("scenes", []):
            unknown = set(scene) - SCENE_KEYS
            if unknown:
                raise AdventureError(f"Scene {scene.get('id')}: unknown keys {sorted(unknown)}")
            sid = scene["id"]
            if sid in self.scenes:
                raise AdventureError(f"Duplicate scene id {sid}")
            self.scenes[sid] = scene
            self.objects[sid], self.items[sid] = {}, {}
            for obj in scene.get("objects", []):
                item = parse_item(obj, sid)
                bucket = self.items[sid] if item.portable else self.objects[sid]
                bucket[item.id] = item
        for t in self.data.get("transitions", []):
            unknown = set(t) - TRANSITION_KEYS
            if unknown:
                raise AdventureError(f"Transition {t.get('id')}: unknown keys {sorted(unknown)}")
            if t["id"] in self.transitions:
                raise AdventureError(f"Duplicate transition id {t['id']}")
            self.transitions[t["id"]] = t

    # ── accessors ───────────────────────────────────────────────────────────
    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def title(self) -> str:
        return self.data.get("title", self.id)

    @property
    def start(self) -> str:
        return self.data["start"]

    @property
    def home(self) -> str:
        return self.data.get("home", self.start)

    @property
    def creatures(self) -> dict[str, dict]:
        return self.data.get("creatures", {})

    @property
    def groups(self) -> dict[str, dict]:
        return self.data.get("groups", {})

    @property
    def encounters(self) -> dict[str, Any]:
        return self.data.get("encounters", {})

    def barrier_scene(self, barrier_id: str) -> str | None:
        for sid, objs in self.objects.items():
            if barrier_id in objs:
                return sid
        return None

    # ── validation ──────────────────────────────────────────────────────────
    def validate(self) -> tuple[list[str], list[str]]:
        """Return (errors, warnings)."""
        errors: list[str] = []
        warnings: list[str] = []
        if self.start not in self.scenes:
            errors.append(f"start scene '{self.start}' does not exist")
        if self.home not in self.scenes:
            errors.append(f"home scene '{self.home}' does not exist")
        ids: dict[str, str] = {}
        for sid in self.scenes:
            for oid in list(self.objects[sid]) + list(self.items[sid]):
                if oid in ids:
                    errors.append(f"object id '{oid}' used in both {ids[oid]} and {sid}")
                ids[oid] = sid
        for tid, t in self.transitions.items():
            for end in ("from", "to"):
                if t.get(end) not in self.scenes:
                    errors.append(f"transition {tid}: unknown {end} scene '{t.get(end)}'")
            if t.get("barrier") and self.barrier_scene(t["barrier"]) not in (t.get("from"), t.get("to")):
                errors.append(f"transition {tid}: barrier '{t['barrier']}' is not an object at either end")
            for end in (t.get("from"), t.get("to")):
                if t.get("one_way") and end == t.get("to"):
                    continue
                if not (t.get("ends") or {}).get(end, {}).get("label"):
                    warnings.append(f"transition {tid}: no label for the exit from {end}")
            for effect in t.get("on_traverse", []):
                self._check_effect(effect, f"transition {tid}", errors)
        for sid, scene in self.scenes.items():
            for obj in list(self.objects[sid].values()) + list(self.items[sid].values()):
                for inter in obj.interactions:
                    for effect in inter.get("effects", []):
                        self._check_effect(effect, f"object {obj.id}", errors)
            for trap in scene.get("traps", []):
                for effect in trap.get("effects", []):
                    self._check_effect(effect, f"trap {trap.get('id')}", errors)
                for tid in trap.get("trigger", {}).get("move", []):
                    if tid not in self.transitions:
                        errors.append(f"trap {trap.get('id')}: unknown transition '{tid}'")
            for g in scene.get("groups", []):
                if g.get("group") not in self.groups:
                    errors.append(f"scene {sid}: unknown group '{g.get('group')}'")
        for gid, group in self.groups.items():
            for member in group.get("members", []):
                if member.get("creature") not in self.creatures:
                    errors.append(f"group {gid}: unknown creature '{member.get('creature')}'")
        for entry in self.encounters.get("table", []):
            if entry.get("group") and entry["group"] not in self.groups:
                errors.append(f"encounter {entry.get('id')}: unknown group '{entry['group']}'")
        if not errors:
            unreachable = set(self.scenes) - self._reachable(self.start)
            for sid in sorted(unreachable):
                errors.append(f"scene '{sid}' cannot be reached from the start")
            for sid in sorted(self.scenes):
                if self.home not in self._reachable(sid):
                    warnings.append(f"no route from '{sid}' back to '{self.home}'")
        return errors, warnings

    def _check_effect(self, effect: dict, where: str, errors: list[str]) -> None:
        if effect.get("op") not in EFFECT_OPS:
            errors.append(f"{where}: unknown effect op '{effect.get('op')}'")

    def _reachable(self, start: str) -> set[str]:
        """Scenes reachable following directions, assuming barriers can be passed."""
        seen, todo = {start}, [start]
        while todo:
            here = todo.pop()
            for t in self.transitions.values():
                nxt = None
                if t["from"] == here:
                    nxt = t["to"]
                elif t["to"] == here and not t.get("one_way"):
                    nxt = t["from"]
                if nxt and nxt not in seen:
                    seen.add(nxt)
                    todo.append(nxt)
        return seen


MAX_ADVENTURE_BYTES = 5_000_000
URL_TIMEOUT_SECONDS = 15


def list_adventures() -> list[dict[str, str]]:
    """Adventures bundled with the project: id and file path."""
    return [{"id": p.parent.name, "path": str(p)} for p in sorted(ADVENTURES_DIR.glob("*/adventure.yaml"))]


def is_url(source: str) -> bool:
    return bool(re.match(r"^https?://", source, re.IGNORECASE))


def normalize_source(source: str) -> str:
    """A URL as given, or a file path made absolute."""
    if is_url(source):
        return source
    path = Path(source).expanduser()
    if path.exists():
        return str(path.resolve())
    return source  # maybe a bundled adventure id


def read_source(source: str) -> str:
    """Read adventure YAML from an http(s) URL, a file, a folder holding
    adventure.yaml, or the id of a bundled adventure."""
    if is_url(source):
        try:
            with urllib.request.urlopen(source, timeout=URL_TIMEOUT_SECONDS) as response:
                data = response.read(MAX_ADVENTURE_BYTES + 1)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise AdventureError(f"Cannot download the adventure from {source}: {exc}") from exc
        if len(data) > MAX_ADVENTURE_BYTES:
            raise AdventureError(f"The adventure at {source} is larger than {MAX_ADVENTURE_BYTES} bytes.")
        return data.decode("utf-8")
    path = Path(source).expanduser()
    if path.is_dir():
        path = path / "adventure.yaml"
    if not path.is_file():
        bundled = ADVENTURES_DIR / source / "adventure.yaml"
        if re.fullmatch(r"[A-Za-z0-9_-]+", source) and bundled.is_file():
            path = bundled
        else:
            raise AdventureError(f"No adventure file at '{source}'.")
    return path.read_text(encoding="utf-8")


def load_adventure(source: str) -> Adventure:
    """Load and validate an adventure from a file path, folder, URL or bundled id."""
    try:
        data = yaml.safe_load(read_source(source))
    except yaml.YAMLError as exc:
        raise AdventureError(f"The adventure is not valid YAML: {exc}") from exc
    if not isinstance(data, dict) or "id" not in data:
        raise AdventureError("The adventure file needs an 'id' and the other top-level keys.")
    adventure = Adventure(data, normalize_source(source))
    errors, _ = adventure.validate()
    if errors:
        raise AdventureError("Invalid adventure:\n  " + "\n  ".join(errors))
    return adventure
