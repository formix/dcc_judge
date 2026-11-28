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
def list_adventures(adventures: str = "") -> str:
    """List the adventures in an adventures directory (default: "adventures"),
    with number, title, whether each is a funnel, and errors for unusable ones."""
    return _dump(_list_adventures(adventures or None))


@mcp.tool()
def saved_game() -> str:
    """Whether a saved game exists, to resume it or start over."""
    store = SaveStore()
    if not store.exists():
        return _dump({"saved_game": False})
    try:
        state = store.load()
    except (ValueError, KeyError) as exc:
        return _dump({"saved_game": True, "ok": False, "errors": [f"The save cannot be read: {exc}"]})
    return _dump({"saved_game": True, "ok": True, "village": state.village, "phase": state.phase,
                  "adventure_source": state.adventure_source})


@mcp.tool()
def reset_game() -> str:
    """Delete the saved game. The next new_game starts from scratch. Logs are kept."""
    global _game
    _game = None
    return _dump({"ok": True, "deleted_save": SaveStore().delete()})


@mcp.tool()
def new_game(adventures: str = "", seed: int | None = None, adventure: str = "") -> str:
    """Start a new game in the village tavern. The adventure is picked among the
    funnels in the adventures directory (default: "adventures"), since a 0-level
    party only gets funnel hooks; `adventure` forces one (file path, URL or
    bundled id). Replaces the saved game. Returns the opening and the context."""
    global _game
    try:
        _game, result = Game.new(adventure or None, seed=seed, adventures_dir=adventures or None)
    except AdventureError as exc:
        return _dump({"ok": False, "errors": [str(exc)]})
    return _dump({**result, "context": _game.context()})


@mcp.tool()
def resume_game() -> str:
    """Resume the saved game. Returns the context."""
    global _game
    if not SaveStore().exists():
        return _dump({"ok": False, "errors": ["There is no saved game."]})
    try:
        _game = Game.load()
    except AdventureError as exc:
        return _dump({"ok": False, "errors": [f"The saved game's adventure cannot be loaded: {exc}"]})
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
def inventory(character: str = "") -> str:
    """The actual inventory of the party, or of one character: equipment slots
    (two hands, body, head), the pack with the slots each item takes, coins,
    and used and free carrying slots. Show it to the player as a list, as is;
    do not narrate or rewrite it. No game time passes."""
    return _dump(_need_game().inventory(character or None))


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
