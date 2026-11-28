"""
DCC JUDGE: console client.

Starts the engine as an MCP server over stdio and plays as the Judge:
- the player's words go to the engine's `command` tool first;
- anything the built-in parser does not understand is interpreted by a model
  (Ollama, local or remote), which sends a proposal to `act`;
- results are narrated by the model, or printed plainly without one.

Usage:
    python src/cli/judge.py ADVENTURE [options]

    ADVENTURE is the adventure file: a path or an http(s) URL.

    python src/cli/judge.py adventures/elders_secret/adventure.yaml
    python src/cli/judge.py adventures/elders_secret/adventure.yaml --model gemma4-12b-128k:latest
    python src/cli/judge.py https://example.com/my_adventure.yaml --model llama3.1 --host http://server:11434
    python src/cli/judge.py adventures/elders_secret/adventure.yaml --reset --seed 7
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys

_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from mcp import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402
from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.prompt import Prompt  # noqa: E402
from rich.text import Text  # noqa: E402

from engine.judge_guide import JUDGE_GUIDE  # noqa: E402

console = Console()

BANNER = r"""
 ██████╗  ██████╗ ██████╗         ██╗██╗   ██╗██████╗  ██████╗ ███████╗
 ██╔══██╗██╔════╝██╔════╝         ██║██║   ██║██╔══██╗██╔════╝ ██╔════╝
 ██║  ██║██║     ██║              ██║██║   ██║██║  ██║██║  ███╗█████╗
 ██║  ██║██║     ██║         ██   ██║██║   ██║██║  ██║██║   ██║██╔══╝
 ██████╔╝╚██████╗╚██████╗    ╚█████╔╝╚██████╔╝██████╔╝╚██████╔╝███████╗
 ╚═════╝  ╚═════╝ ╚═════╝     ╚════╝  ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝
"""

NARRATOR = """\
You are GRIMDAR THE UNYIELDING, Judge of a Dungeon Crawl Classics funnel. Retell
the engine's report as short, grim, vivid narration in the second person, in
the pulp voice of Appendix N. Rules:
- Use ONLY what the report says. Do not add exits, objects, creatures, results
  or secrets. Keep every number of damage and every death.
- Perception "infravision": never mention colour; pictures are unrecognisable.
- Perception "touch": the party is blind; only what is felt, heard, smelled.
- No stage directions, no meta-commentary. At most six sentences. End by asking
  what they do, unless the adventure is over."""

INTERPRETER = JUDGE_GUIDE + """
You are now only the interpreter. Reply with ONE JSON object and nothing else:
either a proposal {"actions": [...]} or {"clarify": "question"}.
"""


class ModelJudge:
    """Interpretation and narration through Ollama (local or remote)."""

    def __init__(self, model: str, host: str | None):
        import ollama
        self.client = ollama.Client(host=host) if host else ollama.Client()
        self.model = model

    def _chat(self, system: str, user: str, json_mode: bool) -> str:
        response = self.client.chat(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            format="json" if json_mode else None,
            think=False,
        )
        return re.sub(r"<think>.*?</think>", "", response.message.content or "", flags=re.S).strip()

    def interpret(self, text: str, context: dict, errors: list[str] | None = None) -> str:
        user = f"CONTEXT:\n{json.dumps(context, ensure_ascii=False)}\n\nPLAYER SAYS: {text}"
        if errors:
            user += "\n\nYOUR LAST PROPOSAL WAS REJECTED:\n- " + "\n- ".join(errors) + "\nFix it."
        return self._chat(INTERPRETER, user, json_mode=True)

    def narrate(self, result: dict) -> str:
        user = (f"PERCEPTION: {result.get('perception')}\nGAME OVER: {result.get('game_over')}\n"
                f"REPORT:\n{result.get('summary', '')}")
        return self._chat(NARRATOR, user, json_mode=False)


# ── output ──────────────────────────────────────────────────────────────────
def show(text: str, title: str = "⚖  THE JUDGE  ⚖", style: str = "red") -> None:
    if text.strip():
        console.print(Panel(Text(text.strip()), title=f"[bold {style}]{title}[/bold {style}]",
                            border_style=style, padding=(1, 2)))


def show_rolls(result: dict) -> None:
    for e in result.get("events", []):
        if e.get("kind") in ("check",):
            console.print(f"  [dim]🎲 {e['text']}[/dim]")


# ── session ─────────────────────────────────────────────────────────────────
class Session:
    def __init__(self, mcp: ClientSession, judge: ModelJudge | None):
        self.mcp = mcp
        self.judge = judge
        self.leader = "You"

    def follow_leader(self, result: dict) -> None:
        """Keep the prompt on the current leader's name."""
        leader = result.get("leader")
        if not leader and result.get("context"):
            leader = next((c["name"] for c in result["context"]["party"] if c["leader"]), None)
        if leader:
            self.leader = leader

    async def call(self, tool: str, **args) -> dict:
        result = await self.mcp.call_tool(tool, arguments=args)
        data = json.loads(result.content[0].text)
        if isinstance(data, dict):
            self.follow_leader(data)
        return data

    def narrate(self, result: dict) -> None:
        show_rolls(result)
        if result.get("clarify"):
            show(result["clarify"])
            return
        summary = result.get("summary", "")
        if self.judge and result.get("ok", True) and summary:
            try:
                show(self.judge.narrate(result))
                return
            except Exception as exc:  # narration failure never repeats the action
                console.print(f"[dim]Narration failed ({exc}); plain report follows.[/dim]")
        show(summary, title="⚖  REPORT  ⚖", style="yellow" if result.get("errors") else "red")

    async def turn(self, text: str) -> dict:
        result = await self.call("command", text=text)
        if result.get("handled", True):
            return result
        if not self.judge:
            return {"ok": False, "summary": "I do not understand. (Type 'help'. Start with --model to let a "
                                            "Judge model interpret free-form commands.)", "errors": ["not understood"]}
        context = result["context"]
        errors = None
        for _ in range(2):
            proposal = self.judge.interpret(text, context, errors)
            result = await self.call("act", proposal=proposal)
            if result.get("ok") or not result.get("errors") or result.get("events"):
                return result
            errors = result["errors"]
        return {"ok": False, "summary": "The Judge could not make sense of that. Try saying it another way.",
                "errors": errors or []}


HELP = """\
Plain commands the engine understands directly:
  look | status | inventory | wait | search [thing]
  go <exit> | sneak <exit> | go <exit> under cover of <noise>
  take | drop | equip | unequip <item> | give <item> to <name>
  light [item] | extinguish <item> | fill <lantern>
  force | break | burn | repair <thing> | pick lock <door>
  heal <name> | buy [n] <item> | sell <item> | haggle <item>
  <verb> <object>  for actions an object offers (e.g. oil door)
  leader <name> (or: <name> leads, make <name> leader) | <name> to the front|rear
  attack <enemy> | all attack | defend | flee <exit>
  <name>, <command>  to have someone else act
  quit
With --model, anything else is interpreted by the Judge model."""


async def set_up_party(session: Session, context: dict) -> None:
    console.print("[bold]Your four peasants[/bold] [dim](Enter keeps the suggestion)[/dim]\n")
    for c in context["party"]:
        console.print(f"[bold cyan]{c['name']}[/bold cyan]: {c['race']} {c['occupation']}, HP {c['hp']}, "
                      f"{c['alignment']}, carrying {', '.join(i['name'] for i in c['hands'] + c['pack'])}; {c['cp']} cp")
        name = Prompt.ask("  Name", default=c["name"]).strip() or c["name"]
        if name != c["name"]:
            await session.call("customize_character", character=c["id"], name=name)
    console.print()


async def run(args) -> None:
    console.print(Text(BANNER, style="bold red"))
    judge = ModelJudge(args.model, args.host) if args.model else None
    mode = f"Judge model: {args.model}" + (f" at {args.host}" if args.host else "") if judge else "No model: plain commands only"
    console.print(Panel(f"{mode}.  Type 'help' for commands, 'quit' to stop.", border_style="dark_red"))
    params = StdioServerParameters(command=sys.executable,
                                   args=[os.path.join(_src_dir, "servers", "engine_server.py")],
                                   env=dict(os.environ))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as mcp:
            await mcp.initialize()
            session = Session(mcp, judge)
            source = args.adventure if re.match(r"^https?://", args.adventure, re.I) else \
                os.path.abspath(os.path.expanduser(args.adventure))
            info = await session.call("adventure_info", adventure=source)
            if not info.get("ok"):
                console.print(f"[red]{chr(10).join(info.get('errors', []))}[/red]")
                return
            console.print(f"[bold]{info['title']}[/bold] [dim]({info['source']})[/dim]")
            for warning in info.get("warnings", []):
                console.print(f"[yellow]Adventure warning: {warning}[/yellow]")
            if args.reset and info["saved_game"]:
                await session.call("reset_game", adventure=source)
                console.print("[dim]The saved game was deleted. Starting over.[/dim]")
                info["saved_game"] = False
            if info["saved_game"]:
                result = await session.call("resume_game", adventure=source)
                console.print("[dim]Resuming your saved game.[/dim]")
                session.narrate({"summary": (await session.call("command", text="look"))["summary"],
                                 "perception": result["context"]["scene"]["perception"], "ok": True})
            else:
                result = await session.call("new_game", adventure=source, seed=args.seed)
                if not result.get("ok", True) and result.get("errors"):
                    console.print(f"[red]{result['errors']}[/red]")
                    return
                await set_up_party(session, result["context"])
                # The first character leads (design 7); the player can change it in game.
                first = (await session.call("get_context"))["party"][0]
                if not first["leader"]:
                    await session.call("command", text=f"leader {first['name']}")
                session.leader = first["name"]
                console.print(f"[dim]{first['name']} leads the party. Change it any time: leader <name>.[/dim]\n")
                session.narrate(result)
            while True:
                try:
                    text = Prompt.ask(f"[bold green]{session.leader}[/bold green]").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not text:
                    continue
                if text.lower() in ("quit", "exit", "q"):
                    break
                if text.lower() in ("help", "?"):
                    show(HELP, title="HELP", style="cyan")
                    continue
                result = await session.turn(text)
                session.narrate(result)
                if result.get("game_over"):
                    console.print("[bold red]The adventure is over.[/bold red]")
                    break
    console.print("[dim]Farewell. Your game is saved.[/dim]")


def main() -> None:
    parser = argparse.ArgumentParser(description="DCC Judge console client")
    parser.add_argument("adventure", help="adventure file: a path or an http(s) URL")
    parser.add_argument("--model", help="Ollama model for the Judge (omit for plain commands only)")
    parser.add_argument("--host", help="Ollama host, e.g. http://localhost:11434 or a remote server")
    parser.add_argument("--reset", "--new", dest="reset", action="store_true",
                        help="delete this adventure's saved game and start a new one")
    parser.add_argument("--seed", type=int, help="dice seed for a new game")
    asyncio.run(run(parser.parse_args()))


if __name__ == "__main__":
    main()
