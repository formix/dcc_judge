"""Integration: talk to the engine over MCP stdio, as a Judge would."""

import asyncio
import os
import json
import sys
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


def test_engine_server_over_stdio(tmp_path):
    async def run():
        params = StdioServerParameters(command=sys.executable,
                                       args=[str(ROOT / "src" / "servers" / "engine_server.py")],
                                       cwd=str(tmp_path), env={**os.environ, "DCC_JUDGE_DATA_DIR": str(tmp_path)})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as session:
                await session.initialize()
                names = {t.name for t in (await session.list_tools()).tools}
                assert {"new_game", "command", "act", "get_context"} <= names

                async def call(tool, **args):
                    result = await session.call_tool(tool, arguments=args)
                    return json.loads(result.content[0].text) if tool != "judge_guide" else result.content[0].text

                folder = str(ROOT / "adventures")
                listed = await call("list_adventures", adventures=folder)
                assert any(a["ok"] and a["funnel"] and a["number"] == "F01" for a in listed)
                assert not (await call("saved_game"))["saved_game"]
                started = await call("new_game", adventures=folder, seed=2)
                assert started["context"]["scene"]["scene"] == "village_tavern"
                assert [a["command"] for a in started["available_actions"]] == ["glean rumors", "visit the shopkeeper"]
                hook = await call("command", text="glean rumors")
                assert any(e["kind"] == "hook" for e in hook["events"])
                assert "take the road" in [a["command"] for a in hook["available_actions"]]
                status = await call("command", text="status")
                assert status["handled"] and "leader" in status["summary"]
                unknown = await call("command", text="sing to the goats")
                assert unknown["handled"] is False
                acted = await call("act", proposal=json.dumps({"actions": [{"type": "look"}]}))
                assert acted["ok"]
                inv = await call("inventory")
                assert inv["display_only"] and len(inv["inventory"]) == 4
                assert {"hands", "body", "head"} == set(inv["inventory"][0]["equipment"])
                assert (await call("saved_game"))["saved_game"]
                reset = await call("reset_game")
                assert reset["ok"] and reset["deleted_save"]
                assert not (await call("saved_game"))["saved_game"]
                assert (await call("resume_game"))["ok"] is False
                assert "PROPOSAL FORMAT" in await call("judge_guide")
    asyncio.run(run())
