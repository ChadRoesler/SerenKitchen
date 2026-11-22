"""The async tests run on asyncio only. anyio's pytest plugin would otherwise try trio too, and a CI runner
with a bare install has no trio to try it on."""
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"


# A kitchen ships knowing no repos: the wall is whatever its yaml lists. This is the wall the tests' kitchens
# are given, a handful of apps with repos, so a folder named after one is that fridge's.
WALL = [{"name": n, "display": d, "group": g, "accent": a, "repo": f"someone/{r}"} for n, d, g, a, r in (
    ("seren-memory", "Memory", "brain", "#ff6e8a", "SerenMemory"),
    ("seren-loci", "Loci", "brain", "#5bc8e8", "SerenLoci"),
    ("seren-margin", "Margin", "auxiliary", "#d1cbba", "SerenMargin"),
    ("seren-probe", "Probe", "auxiliary", "#8fffb4", "SerenProbe"),
    ("seren-theatre", "Theatre", "auxiliary", "#6d2823", "SerenTheatre"),
    ("seren-lyceum", "Lyceum", "auxiliary", "#a17056", "SerenLyceum"),
    ("seren-soma", "Soma", "auxiliary", "#8fbf88", "SerenSoma"),
    ("seren-kitchen", "Kitchen Repo", "auxiliary", "#e0514b", "SerenKitchen"),
    ("seren-carabiner", "Carabiner", "carabiners", "#2f6fb3", "SerenCarabiners"),
    ("seren-sinew", "Sinew", "library", "#c4c4c4", "SerenSinew"),
)] + [{"name": "house", "display": "The House", "group": "house", "accent": "#c9c2d6", "repo": ""}]
# the prefix this wall's fridges share, which a hand leaves off (seren-carabiner: the hand is carabiner)
PREFIX = "seren-"
