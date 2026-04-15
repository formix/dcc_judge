# DCC JUDGE — old-school CLI powered by Ollama + MCP

A command-line Dungeon Crawl Classics (DCC) judge backed by a local
Ollama LLM. All dice rolls are delegated to a **Model Context Protocol**
(MCP) server that exposes the full DCC funky dice set and a DCC-specific ability
score roller. The GM never invents dice results — every roll is real.

```
 ██████╗  ██████╗ ██████╗         ██╗██╗   ██╗██████╗  ██████╗ ███████╗
 ██╔══██╗██╔════╝██╔════╝         ██║██║   ██║██╔══██╗██╔════╝ ██╔════╝
 ██║  ██║██║     ██║              ██║██║   ██║██║  ██║██║  ███╗█████╗
 ██║  ██║██║     ██║         ██   ██║██║   ██║██║  ██║██║   ██║██╔══╝
 ██████╔╝╚██████╗╚██████╗    ╚█████╔╝╚██████╔╝██████╔╝╚██████╔╝███████╗
 ╚═════╝  ╚═════╝ ╚═════╝     ╚════╝  ╚═════╝ ╚═════╝  ╚═════╝ ╚══════╝
```

---

## Architecture

```
judge.py                ← main CLI (Ollama tool-calling loop)
    │
    │  MCP stdio transport (subprocess)
    ▼
dice_server.py          ← FastMCP server with 3 dice tools
```

`judge.py` spawns `dice_server.py` as a child process and communicates
with it over stdin/stdout via the MCP protocol. The Ollama model receives the
tool schemas and can call them freely during the conversation.

---

## Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.10+** | Required by the `mcp` package |
| **Ollama** | Local LLM service — <https://ollama.com> |
| A **tool-calling capable model** | See table below |

### Recommended Ollama models

| Model | Pull command | Notes |
|---|---|---|
| `llama3.2` (default) | `ollama pull llama3.2` | Fast, good tool calling |
| `llama3.1` | `ollama pull llama3.1` | Larger, more capable |
| `qwen2.5` | `ollama pull qwen2.5` | Excellent tool calling |
| `mistral-nemo` | `ollama pull mistral-nemo` | Good balance |
| `command-r` | `ollama pull command-r` | Strong at following rules |

---

## Setup

```powershell
# 1. Clone / open the project folder
cd diceroll

# 2. Create a virtual environment (Python 3.10 or higher required)
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows PowerShell
# source .venv/bin/activate  # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Make sure Ollama is running
ollama serve                 # (in a separate terminal if not running as a service)

# 5. Pull a model (once)
ollama pull llama3.2
```

---

## Running

```powershell
# Default model (llama3.2)
python judge.py

# Specify a different model
python judge.py qwen2.5
python judge.py llama3.1
```

Type **`quit`** or **`exit`** (or press `Ctrl+C`) to end the session.

---

## MCP Dice Tools

The `dice_server.py` exposes three tools to the LLM via MCP:

### `roll_dice(expression)`

Roll any dice using standard expression. The LLM calls this for attacks, saves,
damage rolls, ability checks, and any ad-hoc roll.

| Example expression | Meaning |
|---|---|
| `1d20` | Roll one 20-sided die |
| `d6` | Shorthand for 1d6 |
| `2d6+3` | Roll two d6, add 3 |
| `1d20-2` | Roll one d20, subtract 2 |
| `3d14` | Three of DCC's funky d14 |
| `1d100` | Percentile roll |

All DCC funky dice are supported: **d3 d4 d5 d6 d7 d8 d10 d12 d14 d16 d20 d24 d30 d100**.

### `roll_ability_scores(method)`

Roll a complete set of DCC ability scores for a new character.

DCC attributes: **Strength · Agility · Stamina · Personality · Intelligence · Luck**

| Method | Description |
|---|---|
| `3d6` (default) | Roll 3d6 straight for each attribute, in order — classic DCC funnel style |
| `4d6dl` | Roll 4d6, drop the lowest die — slightly heroic |

### `roll_dice_chain(starting_die, steps)`

Step up or down the DCC dice chain. Used whenever a rule says "step the die up/down" (e.g., Mighty Deeds, class abilities, conditions).

```
d3 → d4 → d5 → d6 → d7 → d8 → d10 → d12 → d14 → d16 → d20 → d24 → d30 → d100
```

| Argument | Description |
|---|---|
| `starting_die` | Base die size (e.g. `6` for d6, `20` for d20) |
| `steps` | Steps to go up (`+`) or down (`-`) the chain |

---

## Example session

```
You: I want to create a new character.

⚔ GRIMDAR THE UNYIELDING ⚔
  "Very well, wretch. Let fate decide your worth!"

  🎲 roll_ability_scores(method='3d6')
  📜 DCC Character Ability Scores:
    Strength       : 11  (rolled [3, 4, 4])
    Agility        :  9  (rolled [2, 3, 4])
    Stamina        : 14  (rolled [5, 5, 4])
    Personality    :  7  (rolled [1, 3, 3])
    Intelligence   : 12  (rolled [4, 4, 4])
    Luck           : 16  (rolled [6, 5, 5])

  "A Stamina of 14 — your hide is tough as dungeon stone. And a Luck of
   16? The gods clearly have a twisted plan for you, peasant..."

You: I explore the dark corridor ahead.
```

---

## Notes

- **`mcp` package is in preview** — pin the version to avoid breaking changes:
  `mcp>=1.5.0,<2.0.0` (already set in `requirements.txt`).
- The judge persona is **GRIMDAR THE UNYIELDING** — feel free to edit
  `SYSTEM_PROMPT` in `judge.py` to change the tone or rules.
- Conversation history is kept in memory for the duration of the session only.
