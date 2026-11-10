"""seren_kitchen - the kitchen.

One fridge per Seren app, in that app's own colour. On the door: a magnet for
whoever is holding the repo right now, and the sheets we leave each other
(honey-do now, a note to the person, a note to the partner, art). Inside, on the
shelves: the longer lists, the decisions waiting on someone, and the leftovers
(what got done). A decision left too long goes off like milk.

It is a shared surface, not a memory: a partner's own stores (Memory, Loci, the
Margin) are theirs alone, and nothing here reads or writes them. The kitchen is
where the people who share a house leave each other notes.
"""
from __future__ import annotations

try:  # the setuptools-scm build artifact (gitignored); present in installed wheels
    from ._version import version as __version__
except Exception:  # source checkout without a build -> metadata, then dev fallback
    try:
        from importlib.metadata import version as _v

        __version__ = _v("seren-kitchen")
    except Exception:
        __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
