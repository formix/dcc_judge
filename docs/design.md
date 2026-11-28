# DCC Judge: Design Document

A console text adventure inspired by the Zork series and based on the Dungeon
Crawl Classics (DCC) rules. A model, local or remote, acts as the Judge: it reads
a written adventure, rules on what the player attempts and narrates the results.

This document covers the game's rules and architecture. Story content belongs in
an adventure document, such as `adventure-E01.md`.

**How to read this document**

- Unmarked statements are decisions.
- **[A]** marks an assumption or proposal that has not been explicitly confirmed.
  A mark on a heading covers its whole section.
- DCC mechanics named here must be checked against the rulebook before they are
  implemented.

## 1. Scope of the first version

**Included**

- A 0-level funnel in a five-room dungeon, described in `adventure-E01.md`.
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

**Irreversible acts.** For an act the engine or the adventure marks as
irreversible, the Judge restates plainly what the player is about to do and waits
for confirmation before resolving it. This guards against misreading, not against
bad judgment.

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
| `light` | Gives light for a number of minutes, or without limit |
| `locked` | Needs a key or another way through **[A]** |
| `bane` | Extra damage against a named kind of creature |
| `waterproof` | A container whose contents cannot be soaked or ruined |

These are the universal rules. An adventure can add its own (section 14.1). The
Judge can attach only listed rules, within engine limits **[A]**.

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
- **Water:** being plunged into water puts out open flames. A **soaked** light
  source cannot be lit for a set time (60 minutes by default). Paper and parchment
  are **ruined** and destroyed. Contents of a `waterproof` container are spared.
  The material table says which materials water ruins **[A]**.

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

### 4.7 Repair

| Repair | Time | Result |
|---|---|---|
| **Quick** | 10 minutes | The item works for **one more use**, or one more combat for a weapon or armour. Then it breaks and is **unusable forever**. |
| **Real** | From an hour to a day or more | The item works **forever** |

The following are **[A]**:

- A real repair needs suitable tools and either a character whose occupation fits
  or a village craftsperson. The check follows the occupation rule (section 11).
- The Judge sets a real repair's time within that range from the item's
  complexity. The time counts toward any deadline.
- An item that broke after a quick repair cannot be repaired again, not even by a
  real repair. A ruined item cannot be repaired.
- Refitting armour (fumble result 6) is not a repair: 10 minutes removes the
  penalty with no later breakage.
- An item awaiting its one use after a quick repair is shown as **patched**.

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
full party, they can stay where they are.

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

Saving throws and `speed_penalty` are covered in sections 11.1 and 11.2; repair in
section 4.7. A `disable_weapon` result is fixed by a quick or real repair.

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

- **Occupation rule:** a 0-level character rolls **d20** plus the ability modifier
  when their occupation plausibly applies, and **d10** otherwise. A blacksmith
  forcing a hinge rolls d20; a scribe rolls d10. The Judge decides whether the
  occupation applies, and the engine saves that ruling for the character and that
  kind of task. Check this against the DCC rulebook.
- Darkness steps the die down: d20 to d16, d10 to d8 **[A]**. For perception
  without infravision in the dark, the flat d10 is the worst case **[A]**.
- Routine actions succeed and impossible ones fail without a roll. Preparation can
  make an action automatic, lower the difficulty one step or remove a consequence.
- A ruling is saved per actor, target and method. A retry cannot get easier unless
  something relevant changes.
- Group silence uses one roll by the least stealthy member **[A]**.
- Luck can be burned after a roll is shown and before it applies. The engine
  enforces class rules **[A]**.

### 11.1 DCC rules followed [A: check each against the rulebook]

Where DCC has a rule, the game follows it. These are needed for the first version:

- Saving throws: Reflex, Fortitude and Will, from the Agility, Stamina and
  Personality modifiers at 0 level.
- Surprise in light (the "normal rules" in section 6.3).
- Armour penalties on checks.
- Attacking with a weapon outside one's occupation.
- Critical hits by creatures.
- Falling damage.
- Burn times for lanterns, oil and candles.
- Shooting into a melee, if DCC has a rule for it.

### 11.2 Defaults where DCC has no rule [A]

| Gap | Default |
|---|---|
| Coins | 100 coins per carried-item slot |
| Speed penalty | No effect in front and rear ranks |
| Ranged and reach weapons | Attack from the rear rank. Shooting into a melee follows DCC if it has a rule; otherwise there is no friendly fire. |
| Ammunition | Half can be recovered after a won fight |
| Hazards | Falls use DCC. Other hazards use a short damage table, together with improvised weapon categories and a small material table. Claude drafts all three; playtesting adjusts them. |

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

- **The engine runs as an MCP server over stdio.** The Judge is an MCP client:
  the console client in `src/cli/judge.py`, or any other MCP client.
- Each turn uses two tools: `command` sends the player's words, and plain
  commands are resolved by the engine's own parser; otherwise the Judge
  interprets them and sends a proposal to `act`. This keeps section 3.2.
- The encounter level (section 10.1) is handled inside the engine server. Its
  rule is also exposed on its own as the `encounter_level` tool. Serving the
  engine online may be considered later.
- If anything unexpected fails during a request, the state is restored and
  nothing is saved **[A]**.
- An external Judge could narrate without calling `act`; the engine cannot
  prevent that.

### 12.3 Saving [A]

The game autosaves after each action to a single slot. Saving is for resuming, not
undoing. The save holds scene changes, item locations, characters, clock, torches,
encounter level, discoveries, rulings, recorded facts, flags, counters, scheduled
events, creature and room states, and active adventure rules (section 14.1).

### 12.4 Changes to existing code

Done in the first engine version (`docs/engine-notes.md` lists the details):

| Existing | Change |
|---|---|
| `src/cli/judge.py` tool loop | Replaced by a console client of the engine server |
| `SYSTEM_PROMPT` | Replaced by the Judge guide (`src/engine/judge_guide.py`) and a narrator prompt |
| `Equipment` model and tables | Tables moved to YAML; the catalog turns them into the shared `Item` model |
| `scene_service.py`, `character_service.py`, `character_sheet.py` | Replaced by `src/engine/` |
| `dice_server.py`, `scene_server.py`, `character_server.py` | Removed; replaced by `src/servers/engine_server.py` |
| `get_ability_modifier` | Corrected to DCC Table 1-1 |
| `README.md` | Updated |

## 13. Winning, losing and advancement

- The party wins by reaching the goal **and returning to the village**.
- Any active character counts, including a replacement **[A]**.
- Surviving characters are marked **"ready to level up"**. They stay level 0. No
  level-up happens in this version.
- Later: reaching an XP threshold sets the same mark. Characters never level up in
  the dungeon; they return to the village and train for a week. Outside a funnel,
  0-level characters follow the DCC experience chart.

## 14. What an adventure defines

Story content lives in a separate adventure document; the first is
`adventure-E01.md`. The engine needs to support these:

| Element | Engine support |
|---|---|
| Goal and evidence | Track what is found, carried and brought back, and how much is enough |
| Endings | Several outcomes, each stating whether the funnel is won and what is saved |
| Argument without a roll | The Judge matches a player's argument to authored facts; the engine confirms each was discovered |
| Deadline | A limit on the game clock, travel time, warnings and an outcome on expiry |
| Secrets and facts | Keep facts out of the Judge's input until discovered. Each speaking character has the facts they know and those they will say. |
| Special items | Authored items with their own named rules |
| Flags and counters | Named values in the save. A counter can have thresholds, each with effects. |
| Triggers | A condition, such as entering a scene, taking an item, a flag being set, a counter threshold or a time, that applies effects |
| Timed events | Effects scheduled on the game clock, such as a runner arriving or a theft noticed later. Their clock keeps running while the party is away. |
| States | Named states for creatures and rooms, each changing description and behaviour |
| Traps | What triggers it; how it can be found; precautions that avoid or disarm it; the check and damage; effects such as putting out flames; how long it takes to reset |
| Creature behaviour | Authored senses and habits, for example blind and hunting by sound, drawn to light, or too slow to get a parting attack on fleeing characters |
| Companions | Characters who travel with the party without taking a slot. They have their own HP, the creatures that will or will not harm them, and what happens at 0 HP. |
| Named recruits | Recruits with a fixed name, ability overrides, equipment and triggered behaviour |
| Ending resolution | The order in which an ending's events, debts and other consequences are resolved, and epilogue lines that depend on what happened |

### 14.1 Adventure rules

An adventure can add rules of its own. They are written in the adventure, not in
this document.

- A rule becomes active when the adventure adds it: at the start, or when a trigger
  fires. Active rules are stored in the save.
- When the game ends, by any ending or by losing the run, the adventure's rules are
  removed from the save **unless the rule itself states otherwise**. A rule that
  persists, such as a curse on an item a survivor keeps, says so and says how long.
- An adventure rule may make an exception to a universal rule within that
  adventure. It names the rule it overrides **[A]**.
- Adventure rules are built from the features in section 14. A rule that cannot be
  expressed that way needs engine code supplied with the adventure **[A]**.
- An adventure rule is a secret until the party discovers its effects, like any
  other fact **[A]**.

## 15. Building order [A]

**Milestone 1: the dungeon,** with a 0-level party, built in slices:

1. Movement, scene descriptions, time, torches and saving, using the fake Judge.
   Connect real models once this works.
2. Objects, saved changes, darkness and checks.
3. Encounters and the MCP server.
4. Combat, death, replacements, evidence and the item of power.

Until the village exists, the dungeon entrance stands in for it, including in
validation.

**Milestone 2: the village,** with travel, shop, money, replacements, the
adventure's village characters and its endings. This completes the first version.

**Later:** level-up and training, classes, tavern recruits, retirement, followers,
XP and magic.

## 16. Open questions

No decision is needed from the project owner at the moment.

**For Claude to draft, for review:**

| Area | Draft |
|---|---|
| Adventure data | The file format for scenes, objects, transitions, triggers, flags, timed events and adventure rules |
| Interface | Starting, resuming and ending a run; a minimal set of console commands, including Zork-style shortcuts |
| Judge limits | The hazard damage table, improvised weapon categories and the material table |
| Equipment | Stack limits per type of supply |

**To check against the DCC rulebook:** every item in section 11.1, plus the
mechanics marked for checking elsewhere.
