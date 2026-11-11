"""The viewer's script leans on the Meninges shell for its polling: watch() and keepingScroll(), nothing of its
own (Chad's ruling, 10 Nov 2026: one mechanism for the whole family, so five one-off styles become one). node,
when the box has it, checks that the script parses."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "seren_kitchen" / "viewer" / "ui" / "scripts.js"


def test_the_polling_is_the_shells():
    js = SCRIPT.read_text(encoding="utf-8")
    assert js.count("watch(") >= 2 and "keepingScroll(" in js          # the wall, the open fridge; the sheet's scroll
    assert "whileVisible: true" in js                                    # a hidden tab asks nothing
    for own in ("setInterval(loadWall", "WALL_SIG", "FRIDGE_SIG", "scrollTop = top"):
        assert own not in js, f"the viewer's own copy is back: {own}"


@pytest.mark.skipif(shutil.which("node") is None, reason="no node on this box")
def test_the_script_parses():
    subprocess.run(["node", "--check", str(SCRIPT)], check=True)
