"""Hands: more than one of a partner on the same board. Each hand is its own magnet with its own starter
and wears the partner's face until given one; a sheet says which hand left it; a name signed in capitals is
the same person as the name in small letters."""
from __future__ import annotations

from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen.app import create_app
from seren_kitchen.config import KitchenConfig
from seren_kitchen.store import Store

FACE = "data:image/png;base64,iVBORw0KGgo="


def store(tmp_path) -> Store:
    return Store(tmp_path / "k.json", [{"name": "seren-memory", "display": "Memory"}, {"name": "seren-carabiner", "display": "Carabiner"}])


def test_each_hand_is_its_own_magnet_and_wears_the_partners_face(tmp_path):
    st = store(tmp_path)
    st.set_magnet("ada", starter="start ada", picture=FACE)
    m = st.set_magnet("ada", hand="carabiner", starter="start the ada in carabiner")
    assert m["label"] == "ada·carabiner" and m["hand"] == "carabiner" and m["picture"] == FACE      # the face came along
    assert m["starter"] == "start the ada in carabiner" and st.magnet("ada")["starter"] == "start ada"
    st.stick("ada", "seren-memory")
    st.stick("ada", "seren-carabiner", hand="carabiner")
    held = {f["name"]: f["held_by"] for f in st.fridges()}
    assert held["seren-memory"] == ["ada"] and held["seren-carabiner"] == ["ada·carabiner"]       # one did not yank the other
    assert len(st.magnets()) == 2
    assert st.drop_magnet("ada", "carabiner") and st.magnet("ada") is not None


def test_a_sheet_says_which_hand_left_it_and_authors_ignore_case(tmp_path):
    st = store(tmp_path)
    a = st.leave(fridge="seren-memory", kind="person", title="from the carabiner me", author="ada", hand="carabiner")
    b = st.leave(fridge="seren-memory", kind="person", title="from CHAD", author="ALEX")
    assert a["hand"] == "carabiner" and b["hand"] == ""
    assert [s["id"] for s in st.sheets(author="alex")] == [b["id"]]                                  # ALEX is alex
    assert st.sheets(author="ALEX")[0]["author"] == "ALEX"                                          # kept as signed


def test_hands_over_http_and_an_older_magnet_survives(tmp_path):
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "s"))
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        c.post("/api/magnets", json={"partner": "ada", "picture": FACE})
        m = c.post("/api/magnets", json={"partner": "ada", "hand": "carabiner", "starter": "the carabiner ada"}).json()
        assert m["label"] == "ada·carabiner" and m["picture"] == FACE
        m = c.post("/api/magnets/ada/stick", json={"fridge": "seren-carabiner", "hand": "carabiner"}).json()
        assert m["fridge"] == "seren-carabiner"
        assert c.get("/api/fridges/seren-carabiner").json()["held_by"] == ["ada·carabiner"]
        s = c.post("/api/fridges/seren-carabiner/sheets", json={"kind": "person", "title": "hi", "author": "ada", "hand": "carabiner"}).json()
        r = c.post(f"/api/sheets/{s['id']}/reply", json={"body": "hi back", "author": "ada", "hand": "kitchen"}).json()
        assert s["hand"] == "carabiner" and r["hand"] == "kitchen"
        assert c.delete("/api/magnets/ada?hand=carabiner").status_code == 200
        assert [x["label"] for x in c.get("/api/magnets").json()] == ["ada"]
    # a magnet written before hands existed has none, and still answers as the partner's only one
    import json
    p = tmp_path / "s" / "kitchen.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["magnets"] = {"ada": {"partner": "ada", "starter": "old", "picture": "", "fridge": None, "x": 1, "y": 2, "since": "2026-01-01T00:00:00"}}
    p.write_text(json.dumps(d), encoding="utf-8")
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        assert c.get("/api/magnets").json()[0] == {**d["magnets"]["ada"], "hand": "", "label": "ada", "state": ""}
