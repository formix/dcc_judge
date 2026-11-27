# DCC Judge: Design Document

A console text adventure inspired by the Zork series and based on the Dungeon
Crawl Classics (DCC) rules. A model, local or remote, acts as the Judge: it reads
a written adventure, rules on what the player attempts and narrates the results.

> **Spoiler warning:** section 15 reveals the adventure's secret. This document
> must never be part of the Judge model's input.

**How to read this document**

- Unmarked statements are decisions.
- **[A]** marks an assumption or proposal that has not been explicitly confirmed.
  A mark on a heading covers its whole section.
- DCC mechanics named here must be checked against the rulebook before they are
  implemented.

## 1. Scope of the first version

**Included**

- A 0-level funnel in a five-room dungeon.
- A village with a tavern and a shopkeeper. The shopkeeper lets the player sell
  and restock. The village and tavern do not count among the five rooms.
- A party of at most four characters.
- Empty slots can be filled with new 0-level characters, in the village or in the
  dungeon.

**Excluded**

- Level-ups, XP tracking, training and class selection.
- Spells, spellburn, corruption and other class magic. Authored magic items are
  allowed.
- Tavern recruits during a funnel, and character retirement.
- Separate torchbearers and porters **[A]**.
- Importing published modules. Adventures are written by hand **[A]**.

## 2. Authority: engine and Judge

The Python engine owns all game state and enforces the hard rules. The Judge makes
rulings and narrates. It can change the game only through operations the engine
checks.

### 2.1 What the Judge may invent

The Judge makes up things the adventure did not predict. For example, a player can
break a chair and use one of its legs as a club.

- **Plausible furnishing:** the Judge may decide that an ordinary object is
  present. The engine records it, and it stays there.
- Invented furnishings are mundane and of little value. An author can close a
  scene to additions **[A]**.
- The Judge cannot invent scenes, transitions, keys, treasure, magic items,
  monsters or anything the adventure's progress depends on **[A]**.

### 2.2 Checked operations [A]

| Operation | Engine check |
|---|---|
| Transform an object | The source exists and is consumed or changed |
| Create a weapon | The Judge picks a category; the engine assigns the damage die |
| Change an object or barrier | The target exists; the change is saved |
| Apply a consequence | Damage, conditions, noise and time stay within limits |
| Record a fact | Anything that must persist, such as a villager's promise |

### 2.3 What the Judge is given

The Judge receives only what the party can currently perceive and has discovered.
This covers descriptions, names, notes, change history and secrets. It does not
receive the full chat history: the engine builds each input from the current
scene, the party, relevant changes and a short window of recent conversation. The
save file is the game's memory.

Judging whether an action is plausible must also work from this limited input.

## 3. Game loop

### 3.1 Outer loop

Only actions that are not free run the outer loop.

1. **Encounter check.** Actions trigger these.
2. **Passive perception checks**, such as an elf's sense for secret doors.
3. **Scene description.**
4. **Player actions and requests.**

Steps 2 and 3 happen once each time a scene is entered, whether for the first time
or on a return. The description includes past changes.

- Encounter checks happen once per full 10 minutes of exploration time, with
  unused minutes carried over **[A]**. They are rolled before the action's results
  apply. An encounter partway through leaves the action unfinished **[A]**.
- Passive checks are rolled secretly by every eligible party member, each with
  their own vision penalty. Each new entry gives another chance at anything still
  undiscovered. A transition costing 0 minutes therefore allows free retries.
- The player can ask for the description again for free **[A]**.
- If an encounter interrupts scene entry, passive checks and the full description
  run when exploration resumes **[A]**.

### 3.2 Handling a player request

1. **Input.** Simple commands, such as inventory or changing leader, go straight
   to the engine.
2. **Interpret.** The model returns proposed actions as structured data: actor,
   action type, target, method, any proposed check and difficulty, and the effects
   of success or failure. It may ask for clarification instead.
3. **Validate.** The model gets one chance to correct an invalid proposal. After
   that, the player is asked to rephrase at no game cost.
4. **Resolve.** The engine rolls, applies effects, advances the clock and saves.
5. **Narrate.** The model receives the perceivable results and cannot change
   state. If narration fails, the engine prints a plain summary without repeating
   or rerolling the action.

Narration can still state something false even though it cannot change the saved
game. Playtesting has to watch for this.

### 3.3 Phases

The engine tracks the current phase, **exploration** or **combat**. Each has its
own allowed actions.

## 4. World model

### 4.1 Scenes and saved changes

The adventure is a graph: scenes are nodes and transitions are links. Scenes keep
permanent description separate from elements that can change, and each element
has an ID.

The original adventure is never modified. Changes are stored per scene in a
separate save file and override the original. The current scene is the original
with its changes applied in order.

```yaml
# adventure
id: study
description: A dusty study with a low, beamed ceiling.   # nothing changeable here
objects:
  - id: oak_chair
    name: Oak chair
    description: A sturdy oak chair faces the desk.
    material: wood

# save
scenes:
  study:
    changes:
      - turn: 7
        op: transform
        target: oak_chair
        description: The oak chair lies in pieces, missing a leg.
        creates: [chair_leg_club]
```

Every item has exactly one location: a scene or a character's inventory. Optional
`read_aloud` text can be shown word for word on a first visit **[A]**.

### 4.2 Items and objects

Scene objects and equipment share **one model [A]**.

**Basic parameters:** `id`, `name`, `description`, `material` **[A: this exact
set]**. Extra behaviour comes from **named rules** that the engine understands.
**Notes** give the Judge context but create no game effect.

| Rule | Purpose |
|---|---|
| `breaks: [kinds]` | The kinds of material the item can break; a pickaxe breaks stone |
| `unbreakable` | Cannot be broken |
| `weapon` | Weapon statistics |
| `light` | Gives light for a number of minutes |
| `locked` | Needs a key or another way through **[A]** |

New rules are added only when an adventure needs them. The Judge can attach only
listed rules, within engine limits **[A]**.

### 4.3 Carrying capacity

Characters carry items in **slots**. The details below are **[A]**.

- Each character has 10 carried-item slots. Equipped weapons and worn armour use
  none.
- An ordinary item uses one slot and a bulky item two. Very large objects are
  carried in hand or dragged.
- Small supplies share a slot up to a limit per type, for example two torches.
- A character with no room cannot pick up an item but can rearrange or drop items.
- Dropped gear stays in its scene.
- Slots replace item `weight` in this version.
- These are separate from the worn-equipment slots in the existing code.

### 4.4 Breaking and burning

- Breaking an object produces an item the Judge deems plausible, plus a broken
  version of the original.
- A broken object cannot be broken again.
- A broken object can still be burned if most of its material is combustible.
- Some objects can be broken only with a tool or magic item that can break that
  kind of thing.
- A material table sets defaults for combustibility and what is needed to break
  each material. An object has one main material **[A]**.
- The Judge rules on whether a method is plausible; the engine rules on whether
  the material allows it **[A]**.
- Integrity (intact, broken) and fire (unburnt, burning, burnt) are tracked
  separately **[A]**.
- Anything burning gives light for a time based on its size. Fire does not spread
  **[A]**.

### 4.5 Transitions

Links are two-way by default and may be one-way.

```yaml
- id: study_to_cellar
  from: study
  to: cellar
  one_way: false        # optional
  barrier: oak_door     # optional, an ordinary object
  minutes: 10           # optional
  ends:                 # optional description of each end
    study:  {description: A low door is set in the north wall.}
    cellar: {description: A door stands at the top of the steps.}
```

Milestone 1 implements `from`, `to`, `one_way`, `barrier`, `minutes` and `ends`.
`hidden: true` and movement rules (climbing, swimming) are added when first needed.

- A barrier's state applies from both ends.
- Movement needs a permitted direction and a passable barrier. A broken barrier is
  passable. A burning one is not until the fire is out or it has burned away.
- A hidden transition is not sent to the Judge until discovered.
- The Judge may change a barrier but cannot create a transition **[A]**.
- Village and tavern scenes use the same format and are marked safe and lit
  **[A]**.

### 4.6 Adventure validation [A]

Check for missing IDs, scenes unreachable from the start and scenes with no route
back to the village. The route checks follow link directions and assume barriers
can be passed. An intentional trap is reported as a warning. Keys, destructible
routes and evidence must still be tested by playing.

## 5. Time

An exploration action takes 10 minutes. Scenes can add their own actions to the
preset list. Each added action defines its cost, any check and its results, using
checked operations and named rules **[A]**.

| Action | Base cost |
|---|---|
| Looking at what is plainly visible, asking the Judge, checking inventory | Free |
| Talking, picking up or dropping something in view, equipping a weapon | Free |
| Moving through a transition | 10 min (an author can change it) |
| Searching one object or area | 10 min |
| Breaking, forcing, lockpicking or another physical task | 10 min |
| Lighting a torch from a flame | Free |
| Unclear, impossible or rejected command | Free |

- A failed attempt still costs time.
- One command may contain several actions, resolved in order. An interruption
  stops the rest.
- The party shares one clock, stays together and does one task at a time. Extra
  helpers give no time saving and no extra rolls.
- Anything that can reveal something hidden, change something or require a roll is
  not free **[A]**.
- A free look never reveals hidden things. Searches, passive abilities and
  authored triggers can.

## 6. Light and darkness

A torch lasts 60 minutes, which is six 10-minute actions in light. Holding a lit
torch requires a free hand.

### 6.1 Torches [A]

- Remaining time is tracked per torch, and only lit torches burn.
- A torch can be lit from a flame for free. Without a flame, a fire-starting item
  is needed; this takes 10 minutes and can fail.
- The player sees the number of unlit torches and the lit torch's stage (bright,
  burning low, guttering), but not the exact minutes.
- A dropped light source stays in its scene and keeps burning unless put out.

### 6.2 Lighting the first torch

At the dungeon entrance, while the party is still outside with enough light, the
first torch lights automatically at no cost. The details below are **[A]**.

- It needs a torch, a fire-starting item and a character with a free hand.
- Its 60 minutes start when it is lit.
- Later relighting without a flame follows the normal rules.
- The shopkeeper warns a party that has no torch or no way to light one, but lets
  it leave. A party without these gets nothing free.

### 6.3 Vision

Elves, dwarves and halflings have infravision. It shows only shapes and outlines
in black and white. Judge descriptions must not mention colour. Drawings and
paintings are unrecognisable.

| | Light | Infravision in the dark | No infravision in the dark |
|---|---|---|---|
| Perception checks | Normal | -1 die (d20 to d16) | d10 |
| Surprised on a d6 | Normal rules | 1-3 | 1-5 |
| Fighting | Normal | -1 die | -1 die and 50% chance of swinging at nothing |
| Time for timed actions | x1 | x2 | x4 |

- If no one can see in the dark, descriptions are limited to what the party can
  feel with their hands. Hearing and smell are also included **[A]**.
- "Dark vision" means infravision, and blind characters count as having no
  infravision **[A]**.
- "-1 die" means one step down the dice chain **[A]**.
- Perception and attack penalties follow the character who rolls **[A]**.
- Free actions stay free in darkness **[A]**.

### 6.4 Perception-filtered descriptions [A]

Each element and transition end has a light description plus `infravision` and
`touch` versions. The engine sends the Judge only the applicable version. The
Judge may draft them during authoring for review. Invented objects get all three
when created. Names, notes and history are filtered too.

## 7. Party and leader

- The party has a designated **leader**.
- The leader sets the surprise die and the time pace for every action, and is the
  default actor when the player names no one.
- Surprise is rolled once for the whole party **[A]**.
- When the light goes out, the Judge recommends making a character with
  infravision the leader. The engine triggers this recommendation, and the player
  decides **[A]**.
- Changing leader is free **[A]**. A dead leader is replaced at once, pausing
  combat if needed **[A]**.

## 8. Characters, death and replacements

- The funnel uses 0-level characters. Racial rules, including infravision, apply.
- Only empty slots can be filled, and only with 0-level characters.
- The player can restock in the village and through authored opportunities in the
  dungeon.
- If all active characters die, the run ends **[A]**.
- Bodies and belongings stay where they fall and can be recovered **[A]**.

### 8.1 Dungeon replacements [A]

| Source | How it works |
|---|---|
| Prisoners | Freed from a cell, cage or work gang |
| Lost explorer | Sole survivor of an earlier expedition, possibly with a clue |
| Petrified or cocooned victim | The party must work out how to release them |
| Deserting servant | A captive helper joins after being persuaded or protected |

The author places each opportunity and the engine generates the character. New
characters arrive with little or no equipment and can be recruited once. With a
full party, they can stay where they are. A villager rescue is one possible
encounter of this kind, not the objective.

### 8.1a Village volunteers

The village offers a **limited** number of replacement volunteers. They are
separate from tavern recruits, who do not appear during a funnel. The details
below are **[A]**.

- Four volunteers per run, never replenished. Dungeon recruits do not count.
- They wait at a village gathering place and cost no money. Travel still counts
  toward the deadline.
- Each is a random 0-level character with occupation gear, but no random gear or
  savings.
- The player sees the next volunteer and may accept or decline. A declined
  volunteer remains the next one.
- They fill empty slots only. A living character cannot be dismissed to make room.
- A volunteer who dies does not return to the supply.

### 8.2 Starting equipment

Each character starts with their occupation gear, **one random piece of gear** and
meagre savings. Before leaving, characters can shop with those savings. There is
no free expedition kit, so light and healing are not guaranteed.

- Savings are 5d12 cp per character.
- The player may pool savings to buy shared supplies **[A]**.
- Shopping before first setting out costs no deadline time **[A]**.
- Replacements receive no free kit or savings **[A]**.
- The random item is rolled on DCC's 1d24 starting equipment selection, in
  `data/tables/starting_equipment.yaml`. Item definitions come from
  `src/rulesets/dcc.py`. The table is not yet checked against the rulebook.
- Table format **[A]:** `kind: items` with a `die`; each entry has `min`, `max`,
  an `item` name matching `WEAPONS` or `GEAR`, and a `quantity`.

### 8.3 The shop

The shopkeeper pays **half** of an item's cost. Negotiation can move the offer by
up to 25 percentage points either way, so it ranges from **25% to 75% of cost**.
Negotiation is resolved by **a single Personality check**, which decides whether
the offer rises, falls or stays the same. The player's argument does not change
the check.

| Check total **[A]** | Offer |
|---|---|
| 15 or more | 75% |
| 6 to 14 | 50% |
| 5 or less | 25% |

- Negotiating is optional; 50% can be accepted without a roll. The player is told
  beforehand that the offer can fall **[A]**.
- Each item, or batch of identical items, gets one negotiation. The result is
  saved. After it, the player takes the new offer or keeps the item **[A]**.
- The leader negotiates unless the player names another character **[A]**.
- Luck burn follows the ability check rules **[A]**.

The following are **[A]**:

- Items are bought at their listed cost. Negotiation applies to selling only.
- Offers are rounded down to a whole copper; identical items sold together are
  rounded once.
- Coins and items with a stated value, such as the 20 gp gem, keep full value and
  are not negotiated.
- Evidence, the item of power and damaged items cannot be sold.
- Invented furnishings, and things made from them, are worth nothing to the shop.
- Ordinary supplies are always available. The adventure limits healing supplies
  and other scarce stock. Sold items need not appear in the shop's stock.
- Trading happens only in the village and takes no game time.

## 9. Combat

The player can give orders to any character. Characters not mentioned follow their
standing order, and the leader acts on what is typed.

### 9.1 Time

- A combat takes **10 minutes in total**, including searching the bodies and
  tightening the party's gear.
- No darkness time multiplier applies. Other vision penalties do **[A]**.
- The time is charged as one block, so a torch does not go out between rounds. It
  goes out after the aftermath **[A]**.
- After a victory, bodies are searched automatically. Searching the rest of the
  scene is a separate action **[A]**.
- Combat time triggers no extra encounter checks **[A]**.

### 9.2 Resolution [A]

- The default standing order is to defend. When a target dies, an attacker moves
  to another reachable enemy. Limited items are not used, weapons are not thrown
  away and stunts are not attempted without an order.
- Unclear orders are clarified before any roll.
- Positions are a front and rear rank. A scene can limit the front rank.
- Initiative is one party roll using the leader's modifier against one roll per
  enemy group.
- The engine resolves attacks, damage, hit points, morale and legal targets from
  authored statistics and behaviour. The Judge interprets orders, rules on stunts
  through checked operations and narrates after results are known.

### 9.3 Zero hit points

- At 0 HP a character appears dead, and the party has a chance to recover the body.
  A Luck check shows whether the character survived.
- **Leaving the body behind without checking for life signs kills the character
  immediately.**
- "Leaving behind" means the party leaves the scene **[A]**.
- The fallen character cannot act and drops anything held. A dropped torch keeps
  burning unless the scene puts it out **[A]**.
- The body must be reached and turned over within 1 hour of game time, normally
  during the 10-minute aftermath of a won fight **[A]**.
- Success leaves the character at 1 HP with a permanent -1 to Strength, Agility or
  Stamina, chosen at random. Failure means death. There is one check **[A]**.
- An unresolved fallen character keeps their party slot **[A]**.
- If every character is down, the run ends **[A]**.
- These mechanics must be checked against the DCC rulebook.

### 9.4 Fleeing

The party can flee, at a price: enemies in contact get a parting attack. The
details below are **[A]**.

- Everyone still standing leaves together.
- The exit must be known, passable and open in that direction.
- Each enemy in contact gets one attack in total against someone it can reach. The
  front rank is exposed first. Darkness penalties apply.
- Before fleeing, a character can spend one combat round reaching and checking a
  fallen companion while enemies keep acting. A survivor is conscious at 1 HP but
  needs one companion's help to leave, and that helper cannot attack that round.
- If fleeing would leave anyone unchecked, the Judge warns that they will die and
  asks for confirmation.
- The author specifies pursuit. By default enemies do not follow during the escape,
  but surviving creatures can be encountered later.
- The combat costs 10 minutes in total, with no automatic body search. Moving
  through the exit costs no further time.

### 9.5 Healing

Characters heal through rest and limited supplies. The details below are **[A]**;
compare them with DCC's natural healing rules.

| Source | Effect | Cost and limits |
|---|---|---|
| Village rest | Each character regains 1 HP | 8 hours plus travel, once per run |
| Healing supplies | One character regains 1d4 HP | One use; 10 minutes in light, with darkness multipliers |

- Village rest counts toward the deadline. Resting in the dungeon restores no HP.
- Healing cannot exceed maximum HP, restore permanent ability loss or revive the
  dead.
- Using supplies is an exploration action. It cannot replace the body recovery
  check; a survivor can be healed afterwards.
- The shop sells only a few supplies, and the adventure may place others. The Judge
  cannot invent them or turn ordinary objects into them.
- The character sheet needs a maximum HP value.

### 9.6 Critical hits and fumbles

The engine rolls on result tables whose entries map to checked effects. Use the
existing DCC tables appropriate to 0-level characters; where one is missing, use
what is available online for now. The project owner can supply their own tables
later.

- A natural 20 is a critical hit. 0-level characters roll 1d4 plus their Luck
  modifier on Crit Table I. The sign of that modifier is **[A]**.
- A natural 1 is a fumble and misses. The die depends on armour (d4 unarmoured;
  otherwise the armour's `fumble` value), and the Luck modifier is **subtracted**.
- A swing at nothing in darkness cannot be a critical hit. A natural 1 still
  fumbles **[A]**.
- The Judge narrates after the effects are resolved and never invents an effect.
- Critical hits by creatures and higher-level characters are not yet covered.

**Current tables:** `data/tables/crit_table_i.yaml` and
`data/tables/fumble_table.yaml`, summarised from
<https://roll20.net/compendium/dcc/Combat> and not yet checked against the
rulebook. That page's Crit Table I stops at "6 or more" and says the core rulebook
has more entries. The tables in `data/tables/` are tracked by Git; the rest of
`data/` is ignored. Check the licence before distributing rulebook-derived tables.

#### Table format [A]

One YAML file per table, in `data/tables/`. Loading YAML requires adding PyYAML to
`requirements.txt`.

| Field | Required | Meaning |
|---|---|---|
| `id` | Yes | Unique name, matching the file name |
| `kind` | Yes | `critical` or `fumble` (item tables: see section 8.2) |
| `source` | Yes | Where the table came from |
| `verified` | No | `true` once compared with the rulebook |
| `entries` | Yes | Results in ascending order |

| Entry field | Required | Meaning |
|---|---|---|
| `min`, `max` | See below | Inclusive range of final rolls. Omit `min` on the first entry and `max` on the last to leave them open. All others need both; one number uses the same value twice. |
| `text` | Yes | Short description given to the Judge for narration. It has no game effect. |
| `effects` | Yes | List of effects, applied in order. `[]` means none beyond the hit or miss. |

Ranges must not overlap or leave gaps.

```yaml
id: example_crit
kind: critical
source: Original example
verified: false
entries:
  - max: 1
    text: A solid extra hit.
    effects:
      - {op: extra_damage, dice: 1d3}
  - min: 2
    text: The target reels and falls.
    effects:
      - op: save
        who: target
        save: reflex
        dc: 10
        on_failure:
          - {op: condition, who: target, name: prone, rounds: 1}
```

`who` is `actor` (the one who rolled the natural 20 or 1) or `target`.

| `op` | Parameters |
|---|---|
| `extra_damage` | `dice`; added to the strike |
| `damage` | `who`, `dice` |
| `weapon_damage` | `who`, optional `bonus`; damage from the actor's own weapon |
| `disarm` | `who` |
| `disable_weapon` | `repair_minutes` |
| `destroy_weapon` | optional `mundane_only` |
| `condition` | `who`, `name`, a duration, optional `only_if: armoured` |
| `save` | `who`, `save`, `dc`, `on_failure` (list of effects) |
| `attack_modifier` | `who`, `value`, `attacks` (number affected) |
| `ac_modifier` | `who`, `value`, `repair_minutes` |
| `defence_opening` | `who`, `enemy_bonus`, `attacks` |
| `lose_actions` | `who`, `rounds` |
| `initiative_last` | `who`, `rounds` |
| `speed_penalty` | `who`, `feet`, `until` |
| `free_attack` | `who`, `trigger` |
| `attack_ally` | `target: random_in_range` |

A duration is `rounds` (a number or dice) or `until`, which is a named event
(`healed`, `action_to_stand`) or a check such as `{check: Agility, dc: 16}`.
`repair_minutes` lasts until that much time is spent repairing.

The loader rejects unknown operations and parameters. A result needing a new effect
requires a new operation in the engine, or a deliberate replacement entry.

**Engine gaps these tables expose:** saving throws; repair as a timed action; and
`speed_penalty`, which has no effect yet with front and rear ranks.

### 9.7 Morale

Morale is checked on specific events, with authored exceptions. The roll is the
**2d6 morale check of old-school D&D**, used here in place of a DCC rule.

| Enemy | Triggers a morale check |
|---|---|
| Group | The first death; half of the enemies dead; the chief's death |
| Single monster with many HP | The first hit; reaching half HP |

- Having a chief gives the group a morale boost. An encounter may have no chief.

The following are **[A]**:

- Each trigger fires once per encounter. Triggers caused by the same attack or
  effect produce **one** check, for example when the first death also leaves half
  the group dead.
- "Half" means half or more of the starting number, including the chief. For a
  single monster, it means HP at or below half its maximum.
- The chief adds +2 to the group's morale score, up to 12. It ends when the chief
  dies, before the check for that death.
- Each creature or group has an authored morale score from 2 to 12.
- A roll equal to or below the score holds; a higher roll fails.
- After two successful checks, enemies fight to the death.
- On a failure, authored behaviour decides whether enemies flee or surrender.
- An author can exempt creatures, such as mindless ones, from morale checks.

## 10. Encounters

A shared dungeon or area table applies, and a scene can replace or disable it.

```yaml
encounters:
  level: 1              # starting range on a d6
  table:
    - {id: rat_pack, weight: 3, group: giant_rats}
    - {id: distant_chanting, weight: 2, event: Voices chant somewhere below.}
    - {id: lost_explorer, weight: 1, npc: explorer, once: true}
```

- Results need not be combat. Creatures have an authored attitude or reaction
  table **[A]**.
- Named characters and limited groups persist. The dead stay dead, and used-up
  entries are removed **[A]**.
- Fixed encounters belong to their scene. Safe scenes have no random encounters
  unless an author adds one **[A]**.
- Check surprise where needed. An encounter need not become a fight **[A]**.

### 10.1 Encounter level

The level carries over between actions. Noise and time in darkness raise it, it
can fade, and silence lowers it.

| Cause | Effect |
|---|---|
| Loud action | +1 **[A]** |
| Each full 10 minutes in darkness | +1 **[A]** |
| Each full 10 minutes in light without loud actions | -1 **[A]** |
| Successful silence on a normally loud action | Cancels the noise |
| Successful silence on another action | -1 |
| Clever preparation, such as oiling a squeaky hinge | Cancels that noise; no reduction |
| Clever silent movement, such as stepping to a smith's hammer beat | Counts as moving silently |

- The level is a d6 range: 2 means an encounter on 1-2. The normal limits are the
  authored starting level and 3 **[A]**.
- A silent action takes no extra time; a successful check earns the benefit.
- A failed silence check gives no benefit **[A]**.
- The Judge decides what cannot be done silently, such as smashing a door.
- Clever silent movement needs no roll. Its source must be active and the player
  must say how they use it **[A]**.
- Preparation must use something the party has. Used supplies and the changed
  object are saved **[A]**.
- With a successful silent action, the -1 replaces that time's normal fade **[A]**.
- Apply noise before the action's checks. Apply darkness increases and fading
  after the checks for the time that earned them **[A]**.

## 11. Ability checks

Authored checks and standard rules come first. Otherwise the Judge chooses an
ability and one of these difficulties:

| Difficulty | Meet or beat |
|---|---|
| Easy | 5 |
| Moderate | 10 |
| Hard | 15 |
| Exceptional | 20 |

- The normal roll is d20 plus the ability modifier. The engine applies class,
  training and darkness rules.
- Routine actions succeed and impossible ones fail without a roll. Preparation can
  make an action automatic, lower the difficulty one step or remove a consequence.
- A ruling is saved per actor, target and method. A retry cannot get easier unless
  something relevant changes.
- Group silence uses one roll by the least stealthy member **[A]**.
- Luck can be burned after a roll is shown and before it applies. The engine
  enforces class rules **[A]**.

## 12. Technical architecture

### 12.1 Models

Both local and remote models are supported. Interpretation and narration go
through one provider-independent interface, starting with one model for both
**[A]**. Model quality is judged by playtesting. Each command, proposal and engine
result is logged **[A]**. A fake Judge returning prepared proposals lets the engine
be tested without a model **[A]**.

The development machine has an RTX 4070 Laptop GPU (8 GB), 31 GB of RAM and
Ollama. No candidate model has been evaluated.

### 12.2 MCP

- The encounter level is handled by an **MCP server over stdio**. Serving it
  online may be considered later.
- The engine calls it; the model does not **[A]**.
- The server is stateless: it receives the current level and events and returns
  the new level, which the engine saves **[A]**.
- The existing dice and scene services are called directly, without MCP **[A]**.
- If the server fails, the action should not be partly saved **[A]**.

### 12.3 Saving [A]

The game autosaves after each action to a single slot. Saving is for resuming, not
undoing. The save holds scene changes, item locations, characters, clock, torches,
encounter level, discoveries, rulings and recorded facts.

### 12.4 Changes to existing code

| Existing | Change needed |
|---|---|
| `src/cli/judge.py` tool loop | Replace with the loops in section 3 |
| `SYSTEM_PROMPT` | Rewrite; remove features excluded from this version |
| `Equipment` model and equipment tables | Move to the shared item model with named rules |
| `scene_service.py` | Selectable leader; add scene, clock and light state; persist |
| `character_sheet.py` | Add maximum HP and carried-item slots |
| `dice_server.py`, `scene_server.py` | Stop using them from the game **[A]** |
| Encounter MCP server | New |
| `README.md` | Update for the new design |

## 13. Winning, losing and advancement

- The party wins by reaching the goal **and returning to the village**.
- Any active character counts, including a replacement **[A]**.
- Surviving characters are marked **"ready to level up"**. They stay level 0. No
  level-up happens in this version.
- Later: reaching an XP threshold sets the same mark. Characters never level up in
  the dungeon; they return to the village and train for a week. Outside a funnel,
  0-level characters follow the DCC experience chart.

## 14. Goal and evidence

**Goal:** prove that the village elder made a pact with a demon, so the elder can
be put on trial.

- There are three pieces of evidence, and any two are enough. **Every pair** must
  prove the elder's part in the pact.
- At least two pieces are reachable without a hidden passage or a particular
  check **[A]**.
- Evidence counts when a survivor carries it to the village. A witness must arrive
  alive, has rules for travel and harm, and takes no party slot **[A]**.
- Learning something is not the same as holding proof. Dropped evidence can be
  recovered **[A]**.
- Losing evidence does not by itself lose the run: failing to find enough leads to
  an ending in section 14.1.
- Returning with enough evidence leads to the village endings in section 14.1.

### 14.1 Village endings

| Party's decision | Elder and daughter | Village leadership | Village alignment |
|---|---|---|---|
| Hide the proof | The priest leaves; the elder lives and takes over | The elder | Chaotic **[A]** |
| Fail to find enough proof within 24 hours | The demon, protecting the elder, makes the priest die in his sleep; the elder lives and takes over | The elder | Chaotic **[A]** |
| Side with the priest and let the trial run | The trial is flawed; the elder is hanged and the daughter dies | The priest | Lawful |
| Intervene during the trial in the elder's favour | The elder is exiled; the priest leaves | The merchants' guild | Neutral |

- Each village alignment gives perks, **not yet defined**.
- The alignment influences the probability of each alignment among future
  recruits.
- Alignment is flavour, not morality. A chaotic village is not necessarily evil,
  and a lawful one is not necessarily good.
- This version saves the village alignment. Perks and recruit probabilities can be
  added with later play **[A]**.
- There is no fight with the priest.
- Whether every ending counts as winning the funnel is open (section 18).

| Example evidence **[A]** | What it proves |
|---|---|
| Pact tablet | Names the elder and records the bargain |
| Letter in the elder's hand | Discusses what the elder owes under the pact |
| Captive witness | Saw the elder make the pact |

**The trial plea.** A relevant argument supported by what the party has learned
succeeds without a roll. Otherwise the trial continues.

- The author lists the facts that can support the plea, and one is enough **[A]**.
  Examples **[A]:** the daughter still depends on the pact; the elder used the
  power only to protect her; the trial is unfair.
- The Judge matches the player's own words to those facts, and the engine confirms
  the party has discovered each one used **[A]**.
- At least one supporting fact can be discovered before the trial without a check
  or hidden passage, for example by meeting the daughter **[A]**.
- Before the trial ends, the Judge may ask for clarification and the player may
  strengthen the argument. The player confirms when finished **[A]**.

### 14.2 Deadline

- The party has **24 hours** to find proof. After that, the priest dies as
  described above.
- Going back to the village and heading into the dungeon again spends **6 hours**.
- The 6 hours cover the whole round trip, 3 hours each way **[A]**.
- The engine tracks the deadline on the game clock, not in real time **[A]**.
  Dungeon actions count toward it, including darkness time multipliers.
- To meet it, the party must be back in the village with the proof before the 24
  hours end **[A]**.
- The clock starts when the party first sets out, and that first journey takes 3
  hours **[A]**.
- Travel burns no torch time and has no encounter checks **[A]**.
- The party is warned that time is running out, but the cause of the threat stays
  hidden. The demon's involvement is not given to the Judge before it can be
  revealed.
- Possible warnings **[A]:** the priest says he will bring the matter to a head by
  this time tomorrow but needs proof first; his health worsens as the deadline
  approaches; the Judge gives warnings when the party returns; the status shows
  the approximate time left.
- Missing the deadline without enough proof reaches the chaotic ending but does
  **not** win the funnel, so no one is marked "ready to level up" **[A]**.

## 15. Adventure secret (spoilers)

- The elder did make a pact with a demon.
- The elder used the power it granted to save his daughter's life when she was an
  infant, 20 years ago.
- The daughter's life **still depends on the pact**.
- The village priest has heard of the pact and wants the elder hanged.

**Handling [A]:** the pact and its motive stay out of the Judge's input until
discovered. The motive is a separate discovery: evidence of the pact does not
reveal why it was made. The priest and elder have separate sets of facts they can
speak about, so the model cannot leak what it was never given.

The truth sets up a moral choice: hanging the elder also costs the daughter's
life. Section 14.1 gives the endings. Open questions are listed in section 18.

## 16. Item of power [A: the whole design]

One powerful item or weapon, with a twist or flaw, is to be found during the
adventure. That requirement is decided; the design below is a proposal.

### Wickdrinker

A narrow black sword with a hilt wrapped in wax-stiffened cord. When it is drawn,
nearby flames lean toward it.

| Aspect | Rule |
|---|---|
| Power: strike | +2 to attack rolls and 1d12 damage |
| Power: bane | An extra 1d6 damage against demons and their servants |
| Flaw: hunger | Each hit costs 5 minutes from one lit torch carried by the party |
| Flaw: darkness | Any hunger that no torch can pay costs the wielder 1 HP per hit |

- **Timing:** the combat's 10 minutes are charged first, then the total hunger.
  This keeps torches lit during the fight.
- **Which torch:** the wielder's own if lit, otherwise another lit torch. Any
  unpaid remainder moves to the next lit torch before costing HP.
- **Unpaid hunger:** each hit with any unpaid portion costs 1 HP. In the dark, that
  damage applies immediately, so it can kill the wielder mid-fight.
- **Discovery:** the player is not told the flaw. The torch's visible stage drops
  and the narration describes the flame bending toward the blade.
- **Limits:** it gives no light, is not required to win and is not evidence. It
  cannot be broken. The wielder can put it down at any time.
- **Why it works here:** it is very strong for a 0-level character, but spends the
  light needed to get home. Using it in the dark with infravision avoids losing
  torch time but costs blood.

The engine needs one new named rule for the hunger and one for the bane. Its
numbers need playtesting. A possible story link, not decided, is that it was made
to enforce demonic debts.

## 17. Building order [A]

**Milestone 1: the dungeon,** with a 0-level party, built in slices:

1. Movement, scene descriptions, time, torches and saving, using the fake Judge.
   Connect real models once this works.
2. Objects, saved changes, darkness and checks.
3. Encounters and the MCP server.
4. Combat, death, replacements, evidence and the item of power.

Until the village exists, the dungeon entrance stands in for it, including in
validation.

**Milestone 2: the village,** with travel, shop, money, replacements, the priest,
the elder and the ending. This completes the first version.

**Later:** level-up and training, classes, tavern recruits, retirement, followers,
XP and magic.

**Test elements the five rooms should cover [A]:** a loop with two routes; a
one-way drop with another way out; a locked or stuck door; a squeaky door and oil;
rhythmic forge hammering; a breakable object; an optional hidden passage; random
encounters and one fixed fight; a darkness hazard; a replacement opportunity;
three pieces of evidence; the item of power. A first torch estimate is four,
for a main route of about 12 timed actions in light.

## 18. Open questions

### Where to resume

**Current topic:** designing the five-room dungeon. It is decided that the project
owner and Claude **design it together**: premise and map first, then one room at a
time, with Claude continuing to question the ideas.

**Next question:** what was this place before the party arrived, and why would
evidence of the elder's pact still be there?

A possible starting structure **[A]** is the five-room dungeon: entrance and
guardian; puzzle or social encounter; setback; climax; revelation or reward. These
are story roles, not a required linear order. See sections 14, 15 and 17 for the
goal, secret and test elements.

### Remaining questions

| Area | Question |
|---|---|
| Endings | Does hiding the proof win the funnel? |
| Endings | What happens to the daughter when the elder lives or is exiled? |
| Endings | How does the party learn that the daughter depends on the pact before deciding? |
| Endings | What perks and recruit probabilities does each alignment give? |
| Story | Who sends the party: the priest or someone else? |
| Endings | How does the party hide the proof: by declaring it, or through actions such as lying to the priest? Can a lie be discovered? |
| Story | What does the demon want, and why is the evidence in this dungeon? |
| Combat | Creature critical hits; saving throws; effect of speed penalties; repair |
| Equipment | Stack limits |
| Village | Healing supply price and stock, filling slots with followers |
| Adventure | The five rooms, encounter table, travel times, ending text |
| Interface | Starting, resuming and ending a run; console commands |
| Judge | Improvised weapon categories, limits on consequences, material table |
| Item of power | Accept, change or replace Wickdrinker |
