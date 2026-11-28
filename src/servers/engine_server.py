"""
DCC Judge engine as an MCP server over stdio.

The Judge (any MCP client: the console client in src/cli/play.py, Claude
Desktop, Claude Code...) calls these tools. The engine checks and resolves
every action; the Judge interprets the player and narrates.

Run:  python src/servers/engine_server.py
"""

import json
import os
import sys

_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from mcp.server.mcpserver import MCPServer  # noqa: E402

from engine.adventure import AdventureError, list_adventures as _list_adventures  # noqa: E402
from engine.encounters import apply_level_events  # noqa: E402
from engine.game import Game  # noqa: E402
from engine.judge_guide import JUDGE_GUIDE  # noqa: E402
from engine.state import SaveStore  # noqa: E402

mcp = MCPServer("DCC Judge Engine", instructions=JUDGE_GUIDE)
_game: Game | None = None


def _dump(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=1)


def _need_game() -> Game:
    if _game is None:
        raise RuntimeError("No game loaded. Call new_game or resume_game first.")
    return _game


@mcp.tool()
def list_adventures() -> str:
    """List the adventures available, and whether each has a saved game."""
    store = SaveStore()
    return _dump([{"id": a, "saved_game": store.exists(a)} for a in _list_adventures()])


@mcp.tool()
def new_game(adventure: str = "elders_secret", seed: int | None = None) -> str:
    """Start a new game (overwrites that adventure's save). Returns the opening
    result and the context. A party of four 0-level characters is rolled."""
    global _game
    try:
        _game, result = Game.new(adventure, seed=seed)
    except AdventureError as exc:
        return _dump({"ok": False, "errors": [str(exc)]})
    return _dump({**result, "context": _game.context()})


@mcp.tool()
def resume_game(adventure: str = "elders_secret") -> str:
    """Load the saved game for an adventure and return the context."""
    global _game
    if not SaveStore().exists(adventure):
        return _dump({"ok": False, "errors": [f"No saved game for '{adventure}'."]})
    _game = Game.load(adventure)
    return _dump({"ok": True, "context": _game.context()})


@mcp.tool()
def get_context() -> str:
    """What the Judge may know now: the perceivable scene, exits, party,
    light, combat and recent history. Secrets are never included."""
    return _dump(_need_game().context())


@mcp.tool()
def command(text: str) -> str:
    """Send the player's words. Plain commands are resolved directly
    ("handled": true). Otherwise the result says so and includes the context:
    interpret it and call `act`. Also answers a pending confirmation."""
    return _dump(_need_game().command(text))


@mcp.tool()
def act(proposal: str) -> str:
    """Resolve a proposal: JSON {"actions": [...]} as described by
    `judge_guide`. Returns the events, a plain summary, the perception mode and
    any errors (on errors nothing more happened; fix and retry once)."""
    return _dump(_need_game().act(proposal))


@mcp.tool()
def customize_character(character: str, name: str = "", gender: str = "", alignment: str = "") -> str:
    """Rename a character or set gender (Male/Female) and alignment
    (Chaotic/Neutral/Lawful). No game time passes."""
    return _dump(_need_game().customize(character, name or None, gender or None, alignment or None))


@mcp.tool()
def character_sheet(character: str) -> str:
    """A full character sheet, including birth augur and ability scores."""
    game = _need_game()
    world = game.world()
    char = world.find_character(character)
    if char is None:
        return _dump({"ok": False, "errors": [f"No character '{character}'."]})
    sheet = char.to_dict()
    sheet["ac"] = world.ac(char)
    sheet["items"] = {slot: [i.label() for i in world.char_items(char.id, slot)] for slot in ("hands", "worn", "pack")}
    return _dump(sheet)


@mcp.tool()
def encounter_level(level: int, start: int, events: list[str]) -> str:
    """The encounter level rule on its own: apply events (loud, silent,
    dark_10, quiet_light_10) to a level and return the new level."""
    return _dump({"level": apply_level_events(level, start, events)})


@mcp.tool()
def judge_guide() -> str:
    """How to act as the Judge: the turn loop, narration rules and the
    proposal format."""
    return JUDGE_GUIDE


@mcp.prompt()
def judge() -> str:
    """Become the Judge for a game run by this engine."""
    return JUDGE_GUIDE


if __name__ == "__main__":
    mcp.run()
