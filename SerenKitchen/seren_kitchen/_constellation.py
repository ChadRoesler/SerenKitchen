"""The family, as fridges: every Seren app with the colour its own Starwright card
declares (each card's `--describe`). A kitchen's yaml can
add fridges, drop them, or recolour one; this is what it starts with.

STDLIB ONLY: the config reads it before anything else is up.
"""
from __future__ import annotations

# name, display, group, accent, GitHub repo
CONSTELLATION = [
    ("seren-lodestar", "Lodestar", "core", "#F5D76E", "ChadRoesler/SerenLodestar"),
    ("seren-observatory", "Observatory", "core", "#f59056", "ChadRoesler/SerenObservatory"),
    ("seren-workbench", "Workbench", "core", "#afdbdb", "ChadRoesler/SerenWorkbench"),
    ("seren-memory", "Memory", "brain", "#ff6e8a", "ChadRoesler/SerenMemory"),
    ("seren-loci", "Loci", "brain", "#5bc8e8", "ChadRoesler/SerenLoci"),
    ("seren-corpus-callosum", "Corpus Callosum", "brain", "#9d7cff", "ChadRoesler/SerenCorpusCallosum"),
    ("seren-hippocampus", "Hippocampus", "brain", "#c9a0dc", "ChadRoesler/SerenHippocampus"),
    ("seren-margin", "Margin", "auxiliary", "#d1cbba", "ChadRoesler/SerenMargin"),
    ("seren-probe", "Probe", "auxiliary", "#8fffb4", "ChadRoesler/SerenProbe"),
    ("seren-theatre", "Theatre", "auxiliary", "#6d2823", "ChadRoesler/SerenTheatre"),
    ("seren-lyceum", "Lyceum", "auxiliary", "#a17056", "ChadRoesler/SerenLyceum"),
    ("seren-soma", "Soma", "auxiliary", "#8fbf88", "ChadRoesler/SerenSoma"),
    ("seren-psycheion", "Psycheion", "auxiliary", "#f2aeb1", "ChadRoesler/SerenPsycheion"),
    # "Kitchen Repo", not "Kitchen": the room holds every fridge, this fridge holds the room's own code
    ("seren-kitchen", "Kitchen Repo", "auxiliary", "#e0514b", "ChadRoesler/SerenKitchen"),
    ("seren-symposium", "Symposium", "desktop", "#a3b18a", "ChadRoesler/SerenSymposium"),
    ("seren-carabiner", "Carabiner", "carabiners", "#2f6fb3", "ChadRoesler/SerenCarabiners"),
    ("seren-starwright", "Starwright", "installer", "#d9b382", "ChadRoesler/SerenStarwright"),
    ("seren-sinew", "Sinew", "library", "#c4c4c4", "ChadRoesler/SerenSinew"),
    ("seren-meninges", "Meninges", "library", "#b8b8c8", "ChadRoesler/SerenMeninges"),
    # the house itself: its sheets live on the big fridge's door and freezer, not on a polaroid
    ("seren-project", "The House", "project", "#c9c2d6", ""),
]


def default_fridges() -> list[dict]:
    return [{"name": n, "display": d, "group": g, "accent": a, "repo": r} for n, d, g, a, r in CONSTELLATION]
