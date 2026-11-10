"""SerenKitchen's identity card. STDLIB ONLY - nothing imported, nothing read.

What an INSTALLED Kitchen answers to `--describe`, so it can be compared with
its Starwright card once that exists. Standard library only, for the reason
every Seren card is: the moment you most want a thing to say its own name is
when its install is broken.
"""
from __future__ import annotations

NAME = "seren-kitchen"
DISPLAY = "Seren Kitchen"
DESCRIPTION = ("The kitchen: a fridge per Seren app, magnets for whoever holds it, "
               "and the notes we leave each other.")

# 7431: after Probe (7430), the next free slot in the family band.
PORT = 7431

GROUP = "auxiliary"

# Tomato: a fridge-magnet red that no other app in the family wears.
ACCENT = "#e0514b"

# Nothing to install first. The freezer's facts (releases, builds) arrive over
# HTTP from whoever knows them; a kitchen with no fridges configured still
# serves its page and says so.
REQUIRES: tuple = ()
EXTRAS: tuple = ()

DESCRIBE = {
    "schema_version": 1,
    "name": NAME,
    "display": DISPLAY,
    "description": DESCRIPTION,
    "port": PORT,
    "group": GROUP,
    "accent": ACCENT,
    "package": "seren-kitchen",
    "requires": list(REQUIRES),
    "extras": list(EXTRAS),
}
