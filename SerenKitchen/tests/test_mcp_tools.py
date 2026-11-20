"""The kitchen's MCP tools, called as plain methods on a Store: no MCP SDK, no HTTP. What a partner can do to
the board through its own door, who it signs as, and what it is refused in plain words."""
from __future__ import annotations

import base64
import inspect

import pytest

from seren_kitchen.mcp.tools import MAX_FACE_BYTES, TOOL_NAMES, KitchenToolImpl
from seren_kitchen.store import KitchenError, Store

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def kitchen(tmp_path, author="ada"):
    st = Store(tmp_path / "k.json", [{"name": "seren-memory", "display": "Memory", "repo": "someone/SerenMemory"},
                                     {"name": "seren-carabiner", "display": "Carabiner", "repo": "someone/SerenCarabiners"}])
    who = {"name": author}
    return KitchenToolImpl(st, author=lambda: who["name"], house=lambda: {"person": "alex", "partner": "ada"}), st, who


def test_every_tool_is_there_described_and_none_takes_an_author(tmp_path):
    k, _, _ = kitchen(tmp_path)
    for name in TOOL_NAMES:
        fn = getattr(k, name)
        assert (fn.__doc__ or "").strip(), f"{name} has no description for the model to read"
        # the door signs with one name; a tool that took one could sign as the person of the house
        assert not {"author", "partner", "as_", "signed"} & set(inspect.signature(fn).parameters), name
    assert len(set(TOOL_NAMES)) == 8


def test_leave_read_reply_and_tick_signed_as_the_one_name(tmp_path):
    k, st, _ = kitchen(tmp_path)
    left = k.kitchen_leave("seren-memory", "digits are in", body="all of them", lines=["check the wheel", "which name? old | new"], hand="memory")
    assert left["ok"] and left["place"] == "door" and left["signed"] == "ada · memory"
    sid = left["sheet"]
    assert st.sheet(sid)["author"] == "ada" and st.sheet(sid)["kind"] == "person"       # a note to the person, by default
    rep = k.kitchen_reply(sid, "the wheel is fine", line=0)
    assert rep["on"] == sid and rep["line"] == 0 and rep["signed"] == "ada"
    full = k.kitchen_sheet(sid)
    assert full["fridge"] == "seren-memory" and full["note"] == "all of them" and full["left"] == 2 and full["waiting"] is True
    assert full["lines"][1] == {"text": "which name", "done": False, "choices": ["old", "new"], "pick": None}
    assert [r["note"] for r in full["stuck_on_it"]] == ["the wheel is fine"] and full["stuck_on_it"][0]["on_line"] == 0
    t = k.kitchen_tick(sid, tick=[0], pick_line=1, pick="new")
    assert t["left"] == 0 and t["lines"][1]["pick"] == "new" and "done" not in t          # deciding is not finishing
    assert k.kitchen_tick(sid, done=True)["place"] == "leftovers"
    assert k.kitchen_tick(sid, done=False)["place"] == "door"


def test_the_wall_and_a_fridge_opened(tmp_path):
    k, st, _ = kitchen(tmp_path)
    st.leave(fridge="seren-memory", kind="person", title="to ada", author="alex", body="x" * 300)
    a = k.kitchen_leave("seren-carabiner", "which clip?", lines=["which? steel | brass"])
    k.kitchen_leave("seren-memory", "the long list", kind="list", lines=["one", "two"])
    k.kitchen_stick("seren-carabiner", hand="carabiner")
    wall = k.kitchen_wall()
    assert wall["house"] == {"person": "alex", "partner": "ada"} and wall["signed_as"] == "ada"
    rows = {f["fridge"]: f for f in wall["fridges"]}
    assert rows["seren-memory"]["sheets"] == 2 and [d["by"] for d in rows["seren-memory"]["door"]] == ["alex"]
    assert rows["seren-carabiner"]["held_by"] == ["ada·carabiner"]
    assert wall["waiting_on_a_pick"] == [{"id": a["sheet"], "fridge": "seren-carabiner", "title": "which clip?", "by": "ada"}]
    assert wall["my_magnets"] == [{"magnet": "ada·carabiner", "on": "seren-carabiner"}]
    f = k.kitchen_fridge("seren-memory")
    assert f["called"] == "Memory" and f["leftovers"] == 0 and [s["title"] for s in f["shelf"]] == ["the long list"]
    assert f["door"][0]["note"].endswith("...") and len(f["door"][0]["note"]) == 203     # cut short on a glance
    k.kitchen_tick(f["shelf"][0]["id"], tick=[0, 1])                                   # every line ticked: finished
    f = k.kitchen_fridge("seren-memory", leftovers=True)
    assert f["shelf"] == [] and [s["title"] for s in f["leftovers"]] == ["the long list"]


def test_a_sheet_whose_choices_are_on_the_sheet_can_be_picked(tmp_path):
    k, st, _ = kitchen(tmp_path)
    d = st.leave(fridge="seren-memory", kind="decision", title="paint", options=["red", "blue"], author="alex")
    assert k.kitchen_sheet(d["id"])["choices"] == ["red", "blue"]
    assert k.kitchen_tick(d["id"], pick="blue")["pick"] == "blue"
    plain = k.kitchen_leave("seren-memory", "no choices here", lines=["a"])
    with pytest.raises(KitchenError, match="pick_line"):
        k.kitchen_tick(plain["sheet"], pick="blue")


def test_refusals_come_in_plain_words(tmp_path):
    k, _, _ = kitchen(tmp_path)
    s = k.kitchen_leave("seren-memory", "hello")["sheet"]
    for call, words in ((lambda: k.kitchen_leave("Seren Memory", "x"), "isn't a fridge slug"),
                        (lambda: k.kitchen_leave("seren-nope", "x"), "no fridge called 'seren-nope'; the wall has seren-memory"),
                        (lambda: k.kitchen_leave("seren-memory", ""), "needs a title"),
                        (lambda: k.kitchen_leave("seren-memory", "x" * 121), "needs a title"),
                        (lambda: k.kitchen_leave("seren-memory", "x", kind="chore"), "a sheet is one of"),
                        (lambda: k.kitchen_leave("seren-memory", "x", body="y" * 4001), "at most 4000"),
                        (lambda: k.kitchen_leave("seren-memory", "x", lines=["l"] * 41), "at most 40"),
                        (lambda: k.kitchen_leave("seren-memory", "x", hand="no/slashes"), "isn't a hand name"),
                        (lambda: k.kitchen_sheet("nope"), "isn't a sheet id"),
                        (lambda: k.kitchen_sheet("0123456789ab"), "no sheet '0123456789ab'"),
                        (lambda: k.kitchen_reply(s, "  "), "say what to stick"),
                        (lambda: k.kitchen_reply(s, "hi", line=4), "no line 4"),
                        (lambda: k.kitchen_tick(s), "give something to change"),
                        (lambda: k.kitchen_tick(s, pick_line=0), "takes both"),
                        (lambda: k.kitchen_tick(s, tick=[9]), "no line 9"),
                        (lambda: k.kitchen_magnet(), "give a starter"),
                        (lambda: k.kitchen_magnet(session="a b"), "isn't a session id"),
                        (lambda: k.kitchen_stick("seren-nope"), "no fridge called")):
        with pytest.raises(KitchenError, match=words):
            call()


def test_a_magnet_its_starter_and_its_face(tmp_path):
    k, st, _ = kitchen(tmp_path)
    m = k.kitchen_magnet(starter="open the door and say hi")
    assert m == {"ok": True, "magnet": "ada", "starter": "open the door and say hi", "face": False, "on": "the counter"}
    pic = tmp_path / "me.png"
    pic.write_bytes(PNG)
    m = k.kitchen_magnet(picture=str(pic))                                              # a path on the kitchen's box
    assert m["face"] and m["starter"] == "open the door and say hi"                     # the starter was left as it was
    face = st.magnet("ada")["picture"]
    assert face.startswith("/api/faces/") and st.face_file(face[len("/api/faces/"):]).read_bytes() == PNG
    other = b"\xff\xd8\xff" + b"\x01" * 20
    k.kitchen_magnet(picture="data:image/jpeg;base64," + base64.b64encode(other).decode())   # a data URL, as the page sends
    assert st.magnet("ada")["picture"] != face
    k.kitchen_magnet(picture=face)                                                      # an old face worn again
    assert st.magnet("ada")["picture"] == face
    assert k.kitchen_magnet(hand="carabiner")["magnet"] == "ada·carabiner" and st.magnet("ada", "carabiner")["picture"] == face


def test_a_face_that_is_not_one_changes_nothing(tmp_path):
    k, st, _ = kitchen(tmp_path)
    k.kitchen_magnet(starter="as it was")
    notes = tmp_path / "notes.txt"
    notes.write_text("not a picture", encoding="utf-8")
    big = tmp_path / "big.png"
    big.write_bytes(PNG + b"\x00" * MAX_FACE_BYTES)
    for path, words in ((str(notes), "isn't a PNG"), (str(big), "a magnet takes one under"), (str(tmp_path / "gone.png"), "can't read")):
        with pytest.raises(KitchenError, match=words):
            k.kitchen_magnet(starter="changed", picture=path, session="sess-0001")
    m = st.magnet("ada")
    assert m["starter"] == "as it was" and not m["picture"] and not m.get("session")     # nothing was half done


def test_a_session_takes_its_seat_through_the_tool(tmp_path):
    k, st, _ = kitchen(tmp_path)
    m = k.kitchen_magnet(session="sess-0001", cwd="/home/someone/SerenCarabiners")
    assert m["magnet"] == "ada·carabiner" and m["hand"] == "carabiner" and m["on"] == "seren-carabiner"     # its repo, from minute one
    assert m["starter"] == "cd /home/someone/SerenCarabiners\nclaude --resume sess-0001" and m["state"] == "live"
    assert m["sign_as"] == "pass hand=carabiner on the kitchen tools"
    # another harness: the kitchen cannot know how to resume it, so the partner says
    m = k.kitchen_magnet(session="sess:0002.b", cwd="/somewhere/else", harness="other", starter="other-harness resume sess:0002.b")
    assert m["magnet"] == "ada·else" and m["starter"] == "other-harness resume sess:0002.b" and m["on"] == "the counter"
    assert st.magnet("ada", "else")["harness"] == "other"


def test_stick_move_and_set_down(tmp_path):
    k, st, _ = kitchen(tmp_path)
    assert k.kitchen_stick("seren-memory") == {"ok": True, "magnet": "ada", "on": "seren-memory"}      # made on the first stick
    assert k.kitchen_stick("seren-carabiner") == {"ok": True, "magnet": "ada", "on": "seren-carabiner", "was_on": "seren-memory"}
    assert k.kitchen_stick() == {"ok": True, "magnet": "ada", "on": "the counter", "was_on": "seren-carabiner"}
    assert st.magnet("ada")["fridge"] is None


def test_the_name_is_asked_on_every_call_and_never_blank(tmp_path):
    k, st, who = kitchen(tmp_path)
    assert k.kitchen_leave("seren-memory", "one")["signed"] == "ada"
    who["name"] = "bea"                                                                  # the house renamed its partner from the page
    assert k.kitchen_leave("seren-memory", "two")["signed"] == "bea" and k.kitchen_wall()["signed_as"] == "bea"
    who["name"] = "  "
    assert k.kitchen_leave("seren-memory", "three")["signed"] == "the partner"
