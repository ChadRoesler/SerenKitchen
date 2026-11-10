"""The kitchen's state on its own: sheets get left, ticked, finished, picked and taken down; magnets stick
and stay; the file is whole after every write and comes back the same."""
from __future__ import annotations

import json

import pytest

from seren_kitchen._constellation import default_fridges
from seren_kitchen.store import HOUSEWARMING, KitchenError, Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "kitchen.json", default_fridges(), sour_after_days=7)


def test_a_new_kitchen_has_the_housewarming_note_and_nothing_else(store):
    sheets = store.sheets()
    assert len(sheets) == 1 and sheets[0]["title"] == HOUSEWARMING["title"] and sheets[0]["fridge"] == "seren-kitchen"
    assert sheets[0]["place"] == "door" and sheets[0]["author"] == "the kitchen"


def test_a_sheet_sits_where_its_kind_says(store):
    now = store.leave(fridge="seren-memory", kind="now", title="fix the ugly g", author="ada")
    lst = store.leave(fridge="seren-memory", kind="list", title="honey-do", lines=["a", "b"], author="alex")
    art = store.leave(fridge="seren-memory", kind="art", title="a doodle", author="alex")
    assert (now["place"], lst["place"], art["place"]) == ("door", "shelf", "crisper")
    f = next(f for f in store.fridges() if f["name"] == "seren-memory")
    assert f["counts"] == {"door": 1, "shelf": 1, "crisper": 1, "leftovers": 0}


def test_ticking_every_line_finishes_the_sheet_into_the_leftovers(store):
    s = store.leave(fridge="seren-loci", kind="list", title="two things", lines=["one", "two"])
    s = store.change(s["id"], tick=[0])
    assert s["open_lines"] == 1 and s["place"] == "shelf" and s["done_at"] is None
    s = store.change(s["id"], tick=[1])
    assert s["open_lines"] == 0 and s["place"] == "leftovers" and s["done_at"]
    s = store.change(s["id"], done=False)                     # back where its kind sits
    assert s["place"] == "shelf" and s["done_at"] is None
    s = store.change(s["id"], untick=[0])
    assert s["open_lines"] == 1


def test_a_thought_is_done_when_you_say_so(store):
    s = store.leave(fridge="seren-soma", kind="person", title="the fridge is ours")
    assert s["lines"] == [] and s["done_at"] is None
    s = store.change(s["id"], done=True)
    assert s["place"] == "leftovers"


def test_a_line_can_carry_choices_and_a_pick_finishes_the_line(store):
    s = store.leave(fridge="seren-lyceum", kind="now", title="today", lines=["eat", "which arm? probe | memory | both", {"text": "sleep"}])
    assert s["lines"][1]["options"] == ["probe", "memory", "both"] and s["lines"][1]["pick"] is None
    assert "options" not in s["lines"][0] and s["waiting"] is True
    assert [x["id"] for x in store.sheets(waiting=True)] == [s["id"]]
    with pytest.raises(KitchenError, match="no choices"):
        store.change(s["id"], pick_line={"line": 0, "option": "x"})
    with pytest.raises(KitchenError, match="one of"):
        store.change(s["id"], pick_line={"line": 1, "option": "x"})
    s = store.change(s["id"], pick_line={"line": 1, "option": "both"})
    assert s["lines"][1]["pick"] == "both" and s["lines"][1]["done"] and s["waiting"] is False and s["done_at"] is None
    assert store.sheets(waiting=True) == []
    # a dict line with options, picked already
    t = store.leave(fridge="seren-lyceum", kind="now", title="t", lines=[{"text": "q", "options": ["a", "b"], "pick": "b"}])
    assert t["lines"][0]["pick"] == "b" and t["waiting"] is False


def test_a_sheet_without_a_title_takes_one_from_its_note_or_first_line(store):
    s = store.leave(fridge="seren-margin", kind="person", title="", body="thank you for the macaroni.\nit is on the fridge.")
    assert s["title"] == "thank you for the macaroni."
    s = store.leave(fridge="seren-margin", kind="list", title="  ", lines=["milk", "eggs"])
    assert s["title"] == "milk"
    with pytest.raises(KitchenError, match="something to read"):
        store.leave(fridge="seren-margin", kind="person", title="")


def test_a_decision_needs_options_and_a_pick_finishes_it(store):
    with pytest.raises(KitchenError, match="needs choices"):
        store.leave(fridge="seren-lyceum", kind="decision", title="the consolidator", options=["a"])
    d = store.leave(fridge="seren-lyceum", kind="decision", title="the consolidator", options=["a", "b", "c"], author="ada")
    assert d["place"] == "door" and d["sour"] is False
    with pytest.raises(KitchenError, match="one of the options"):
        store.change(d["id"], pick="z")
    d = store.change(d["id"], pick="b")
    assert d["pick"] == "b" and d["done_at"] is None and d["place"] == "door"      # deciding is not finishing


def test_a_decision_left_too_long_goes_sour(tmp_path):
    st = Store(tmp_path / "k.json", default_fridges(), sour_after_days=0)    # sour the moment it is made
    d = st.leave(fridge="seren-probe", kind="decision", title="which arm", options=["x", "y"])
    import time; time.sleep(0.01)
    assert st.sheet(d["id"])["sour"] is True
    assert next(f for f in st.fridges() if f["name"] == "seren-probe")["sour"] == 1
    st.change(d["id"], pick="x")
    assert st.sheet(d["id"])["sour"] is False                 # picked: milk's fine


def test_what_the_kitchen_refuses(store):
    with pytest.raises(KitchenError, match="no fridge"):
        store.leave(fridge="seren-nope", kind="now", title="x")
    with pytest.raises(KitchenError, match="one of"):
        store.leave(fridge="seren-memory", kind="sticky", title="x")
    with pytest.raises(KitchenError, match="needs a title"):
        store.leave(fridge="seren-memory", kind="now", title="   ")
    s = store.leave(fridge="seren-memory", kind="now", title="x", lines=["a"])
    with pytest.raises(KitchenError, match="no line"):
        store.change(s["id"], tick=[4])
    with pytest.raises(KitchenError, match="only a decision"):
        store.change(s["id"], pick="a")
    with pytest.raises(KitchenError, match="no sheet"):
        store.change("deadbeef", title="y")


def test_magnets_stick_stay_and_remember_where_they_were(store):
    m = store.set_magnet("ada", starter="start the partner")
    assert m["fridge"] is None and m["starter"] == "start the partner"
    m = store.stick("ada", "seren-memory", x=20, y=15)
    assert m["fridge"] == "seren-memory" and m["x"] == 20 and m["since"]
    assert next(f for f in store.fridges() if f["name"] == "seren-memory")["held_by"] == ["ada"]
    m = store.stick("ada", "seren-soma")
    assert m["fridge"] == "seren-soma" and m["last"] == "seren-memory"
    m = store.stick("ada", None)                              # onto the counter
    assert m["fridge"] is None and m["last"] == "seren-soma"
    store.stick("other", "seren-soma")                         # a magnet that was never made is made by sticking
    assert store.magnet("other")["fridge"] == "seren-soma"
    with pytest.raises(KitchenError, match="no fridge"):
        store.stick("ada", "seren-nope")
    with pytest.raises(KitchenError, match="data URL"):
        store.set_magnet("ada", picture="http://elsewhere/face.png")
    assert store.drop_magnet("other") and not store.drop_magnet("other")


def test_facts_on_the_freezer(store):
    f = store.set_facts("seren-memory", release="5.6.1", build="ok")
    assert f["release"] == "5.6.1" and f["build"] == "ok" and f["checked_at"]
    f = store.set_facts("seren-memory", build=None)
    assert "build" not in f and f["release"] == "5.6.1"
    assert next(x for x in store.fridges() if x["name"] == "seren-memory")["facts"]["release"] == "5.6.1"


def test_the_file_is_whole_and_comes_back_the_same(tmp_path):
    path = tmp_path / "kitchen.json"
    st = Store(path, default_fridges())
    s = st.leave(fridge="seren-margin", kind="self", title="remember the milk", lines=["milk"], author="ada")
    st.stick("ada", "seren-margin")
    st.set_facts("seren-margin", release="5.3.0")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert set(raw) == {"facts", "magnets", "sheets"} and s["id"] in raw["sheets"]
    again = Store(path, default_fridges())
    assert again.sheet(s["id"])["title"] == "remember the milk"
    assert again.magnet("ada")["fridge"] == "seren-margin"
    assert len(again) == 2                                     # the housewarming note and this one
    assert not list(path.parent.glob("*.tmp"))                 # nothing half-written left behind


def test_a_corrupt_file_is_set_aside_not_fatal(tmp_path):
    path = tmp_path / "kitchen.json"
    path.write_text("{not json", encoding="utf-8")
    st = Store(path, default_fridges())
    assert len(st) == 1 and (tmp_path / "kitchen.json.unreadable").exists()


def test_take_down(store):
    s = store.leave(fridge="seren-theatre", kind="now", title="oops")
    assert store.take_down(s["id"]) and store.sheet(s["id"]) is None and not store.take_down(s["id"])
