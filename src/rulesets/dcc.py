"""
DCC ruleset constants.

Central place for all Dungeon Crawl Classics rule data:
races, classes, the dice chain, and ability score names.
"""

# DCC playable races.
CHARACTER_RACES: dict[str, float] = {"Human": 0.7, "Elf": 0.1, "Halfling": 0.1, "Dwarf": 0.1}
# Each race maps to a list of (occupation, trained_weapon, trade_good) tuples.
CHARACTER_OCCUPATIONS: dict[str, list[tuple[str, str, str]]] = {
    "Human": [
        ("Alchemist",            "Staff",                  "Oil, 1 flask"),
        ("Animal trainer",       "Club",                   "Pony"),
        ("Armorer",              "Hammer (as club)",        "Iron helmet"),
        ("Astrologer",           "Dagger",                 "Spyglass"),
        ("Barber",               "Razor (as dagger)",      "Scissors"),
        ("Beadle",               "Staff",                  "Holy symbol"),
        ("Beekeeper",            "Staff",                  "Jar of honey"),
        ("Blacksmith",           "Hammer (as club)",       "Steel tongs"),
        ("Butcher",              "Cleaver (as axe)",       "Side of beef"),
        ("Caravan guard",        "Short sword",            "Linen, 1 yard"),
        ("Cheesemaker",          "Cudgel (as staff)",      "Stinky cheese"),
        ("Cobbler",              "Awl (as dagger)",        "Shoehorn"),
        ("Confidence artist",    "Dagger",                 "Quality cloak"),
        ("Cooper",               "Crowbar (as club)",      "Barrel"),
        ("Costermonger",         "Knife (as dagger)",      "Fruit"),
        ("Cutpurse",             "Dagger",                 "Small chest"),
        ("Ditch digger",         "Shovel (as staff)",      "Fine dirt, 1 lb."),
        ("Dock worker",          "Pole (as staff)",        "1 late RPG book"),
        ("Farmer",               "Pitchfork (as spear)",   "Hen"),
        ("Fortune-teller",       "Dagger",                 "Tarot deck"),
        ("Gambler",              "Club",                   "Dice"),
        ("Gongfarmer",           "Trowel (as dagger)",     "Sack of night soil"),
        ("Grave digger",         "Shovel (as staff)",      "Trowel"),
        ("Guild beggar",         "Sling",                  "Crutches"),
        ("Healer",               "Club",                   "Holy water, 1 vial"),
        ("Herbalist",            "Club",                   "Herbs, 1 lb."),
        ("Herder",               "Staff",                  "Herding dog"),
        ("Hunter",               "Shortbow",               "Deer pelt"),
        ("Indentured servant",   "Staff",                  "Locket"),
        ("Jester",               "Dart",                   "Silk clothes"),
        ("Jeweler",              "Dagger",                 "Gem worth 20 gp"),
        ("Locksmith",            "Dagger",                 "Fine tools"),
        ("Mendicant",            "Club",                   "Cheese dip"),
        ("Mercenary",            "Longsword",              "Hide armor"),
        ("Merchant",             "Dagger",                 "4 gp, 14 sp, 27 cp"),
        ("Miller/baker",         "Club",                   "Flour, 1 lb."),
        ("Minstrel",             "Dagger",                 "Ukulele"),
        ("Noble",                "Longsword",              "Gold ring worth 10 gp"),
        ("Orphan",               "Club",                   "Rag doll"),
        ("Ostler",               "Staff",                  "Bridle"),
        ("Outlaw",               "Short sword",            "Leather armor"),
        ("Rope maker",           "Knife (as dagger)",      "Rope, 100'"),
        ("Scribe",               "Dart",                   "Parchment, 10 sheets"),
        ("Shaman",               "Mace",                   "Herbs, 1 lb."),
        ("Slave",                "Club",                   "Strange-looking rock"),
        ("Smuggler",             "Sling",                  "Waterproof sack"),
        ("Soldier",              "Spear",                  "Shield"),
        ("Squire",               "Longsword",              "Steel helmet"),
        ("Tax collector",        "Longsword",              "100 cp"),
        ("Trapper",              "Sling",                  "Badger pelt"),
        ("Urchin",               "Stick (as club)",        "Begging bowl"),
        ("Wainwright",           "Club",                   "Pushcart"),
        ("Weaver",               "Dagger",                 "Fine suit of clothes"),
        ("Wizard's apprentice",  "Dagger",                 "Black grimoire"),
        ("Woodcutter",           "Handaxe",                "Bundle of wood"),
    ],
    "Elf": [
        ("artisan",        "Staff",                  "Clay, 1 lb."),
        ("barrister",      "Quill (as dart)",        "Book"),
        ("chandler",       "Scissors (as dagger)",   "Candles, 20"),
        ("falconer",       "Dagger",                 "Falcon"),
        ("forester",       "Staff",                  "Herbs, 1 lb."),
        ("glassblower",    "Hammer (as club)",        "Glass beads"),
        ("navigator",      "Shortbow",               "Spyglass"),
        ("sage",           "Dagger",                 "Parchment and quill pen"),
    ],
    "Halfling": [
        ("chicken butcher", "Handaxe",            "Chicken meat, 5 lbs."),
        ("dyer",            "Staff",              "Fabric, 3 yards"),
        ("glovemaker",      "Awl (as dagger)",    "Gloves, 4 pairs"),
        ("wanderer",        "Sling",              "Hex doll"),
        ("haberdasher",     "Scissors (as dagger)", "Fine suits, 3 sets"),
        ("mariner",         "Knife (as dagger)",  "Sailcloth, 2 yards"),
        ("moneylender",     "Short sword",        "5 gp, 10 sp, 200 cp"),
        ("trader",          "Short sword",        "20 sp"),
        ("vagrant",         "Club",               "Begging bowl"),
    ],
    "Dwarf": [
        ("apothecarist",     "Cudgel (as staff)",  "Steel vial"),
        ("blacksmith",       "Hammer (as club)",    "Mithril, 1 oz."),
        ("chest-maker",      "Chisel (as dagger)", "Wood, 10 lbs."),
        ("herder",           "Staff",              "Sow"),
        ("miner",            "Pick (as club)",     "Lantern"),
        ("mushroom-farmer",  "Shovel (as staff)",  "Sack"),
        ("rat-catcher",      "Club",               "Net"),
        ("stonemason",       "Hammer",             "Fine stone, 10 lbs."),
    ],
}

# Weapon stats. Peasant-tool entries use the damage and cost of the like weapon.
# cost_cp is in copper pieces: 1 gp = 100 cp, 1 sp = 10 cp.
WEAPONS: list[Equipment] = [
    # ── Core weapons ─────────────────────────────────────────────────────────
    Equipment(name="Club",        cost_cp=3,     damage="1d4"),  #   3 cp
    Equipment(name="Dagger",      cost_cp=300,   damage="1d4"),  #   3 gp
    Equipment(name="Dart",        cost_cp=5,     damage="1d4"),  #   5 cp
    Equipment(name="Handaxe",     cost_cp=400,   damage="1d6"),  #   4 gp
    Equipment(name="Hammer",      cost_cp=500,   damage="1d8"),  #   5 gp  (warhammer; Dwarf stonemason)
    Equipment(name="Longsword",   cost_cp=1000,  damage="1d8"),  #  10 gp
    Equipment(name="Mace",        cost_cp=500,   damage="1d6"),  #   5 gp
    Equipment(name="Short sword", cost_cp=700,   damage="1d6"),  #   7 gp
    Equipment(name="Shortbow",    cost_cp=2500,  damage="1d6"),  #  25 gp
    Equipment(name="Sling",       cost_cp=200,   damage="1d4"),  #   2 gp
    Equipment(name="Spear",       cost_cp=300,   damage="1d8"),  #   3 gp
    Equipment(name="Staff",       cost_cp=50,    damage="1d4"),  #   5 sp
    # ── Peasant tools (damage and cost of like weapon) ────────────────────────
    Equipment(name="Awl (as dagger)",       cost_cp=300,  damage="1d4"),  # like Dagger
    Equipment(name="Chisel (as dagger)",    cost_cp=300,  damage="1d4"),  # like Dagger
    Equipment(name="Cleaver (as axe)",      cost_cp=400,  damage="1d6"),  # like Handaxe
    Equipment(name="Crowbar (as club)",     cost_cp=3,    damage="1d4"),  # like Club
    Equipment(name="Cudgel (as staff)",     cost_cp=50,   damage="1d4"),  # like Staff
    Equipment(name="Hammer (as club)",      cost_cp=3,    damage="1d4"),  # like Club
    Equipment(name="Knife (as dagger)",     cost_cp=300,  damage="1d4"),  # like Dagger
    Equipment(name="Pick (as club)",        cost_cp=3,    damage="1d4"),  # like Club
    Equipment(name="Pitchfork (as spear)",  cost_cp=300,  damage="1d8"),  # like Spear
    Equipment(name="Pole (as staff)",       cost_cp=50,   damage="1d4"),  # like Staff
    Equipment(name="Quill (as dart)",       cost_cp=5,    damage="1d4"),  # like Dart
    Equipment(name="Razor (as dagger)",     cost_cp=300,  damage="1d4"),  # like Dagger
    Equipment(name="Scissors (as dagger)",  cost_cp=300,  damage="1d4"),  # like Dagger
    Equipment(name="Shovel (as staff)",     cost_cp=50,   damage="1d4"),  # like Staff
    Equipment(name="Stick (as club)",       cost_cp=3,    damage="1d4"),  # like Club
    Equipment(name="Trowel (as dagger)",    cost_cp=300,  damage="1d4"),  # like Dagger
]


# All DCC classes. Humans choose from Warrior/Wizard/Cleric/Thief.
# Non-human races (Elf, Halfling, Dwarf) use their race name as their class.
CHARACTER_CLASSES: list[str] = ["Warrior", "Wizard", "Cleric", "Thief", "Elf", "Halfling", "Dwarf"]

ALIGNEMENTS: list[str] = ["Chaotic", "Neutral", "Lawful"]

GENDERS: list[str] = ["Male", "Female"]

# Equipment slots. ring_left / ring_right are the two ring slots.
# Items tagged 'two-handed' require both 'weapon' and 'shield' to be empty.
SLOTS: list[str] = [
    "head", "shoulder", "back", "body",
    "weapon", "shield",
    "ring_left", "ring_right",
    "neck", "feet", "belt",
]

# The full DCC dice chain, weakest → strongest.
DICE_CHAIN: list[int] = [3, 4, 5, 6, 7, 8, 10, 12, 14, 16, 20, 24, 30, 100]

# DCC ability names differ from standard D&D.
CHARACTER_ABILITIES: list[str] = [
    "Strength",
    "Agility",      # DCC uses Agility, not Dexterity
    "Stamina",      # DCC uses Stamina, not Constitution
    "Personality",  # DCC uses Personality, not Wisdom
    "Intelligence",
    "Luck",         # Unique to DCC — used for Luck burns and checks
]

ABILITY_MODIFIERS: dict[int, int] = {
    3: -3,
    4: -2,
    5: -2,
    6: -1,
    7: -1,
    8: -1,
    9: 0,
    10: 0,
    11: 0,
    12: 0,
    13: +1,
    14: +1,
    15: +1,
    16: +2,
    17: +2,
    18: +3,
    19: +3,
    20: +4,
    21: +4,
    22: +5,
    23: +6,
    24: +7,
    25: +8,
}
