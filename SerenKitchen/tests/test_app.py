"""The kitchen over HTTP: the wall in one call, a fridge opened, sheets left and changed, magnets stuck,
the bearer kept, the fonts public, the page rendered in the family's shell."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen._describe import ACCENT, PORT
from seren_kitchen.app import FEATURES, create_app
from seren_kitchen.config import FontsConfig, KitchenConfig, load_config


def client(tmp_path, bearer: str = "", fonts: FontsConfig | None = None) -> TestClient:
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=PORT, bearer_token=bearer),
                        state_dir=str(tmp_path / "state"), fonts=fonts or FontsConfig())
    return TestClient(create_app(cfg, run_freezer=False))


def test_a_reply_sticks_to_its_sheet_and_comes_down_with_it(tmp_path):
    with client(tmp_path) as c:
        s = c.post("/api/fridges/seren-memory/sheets", json={"kind": "person", "title": "to ada", "lines": ["digits!", "git versions"], "author": "alex"}).json()
        r = c.post(f"/api/sheets/{s['id']}/reply", json={"kind": "other", "title": "digits are in", "line": 0, "author": "ada"})
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["reply_to"] == s["id"] and rep["reply_line"] == 0 and rep["fridge"] == "seren-memory"
        top = c.get("/api/sheets", params={"fridge": "seren-memory"}).json()
        assert [x["id"] for x in top] == [s["id"]]                              # the reply is not its own row
        assert [x["id"] for x in top[0]["replies"]] == [rep["id"]]
        assert c.get("/api/sheets", params={"fridge": "seren-memory", "replies": "true"}).json().__len__() == 2
        assert c.post(f"/api/sheets/{s['id']}/reply", json={"title": "x", "line": 7}).status_code == 400
        assert c.post("/api/sheets/nope/reply", json={"title": "x"}).status_code == 404
        c.delete(f"/api/sheets/{s['id']}")
        assert c.get(f"/api/sheets/{rep['id']}").status_code == 404           # came down with its parent


def test_a_migrated_sheet_keeps_its_date_ref_and_body(tmp_path):
    with client(tmp_path) as c:
        s = c.post("/api/fridges/seren-probe/sheets", json={"kind": "list", "title": "probe-suites", "lines": ["Run all tests or a subset"],
                                                           "body": "the long detail", "ref": "probe-suites", "made": "2026-10-20T00:00:00", "author": "punch list"}).json()
        assert s["made"] == "2026-10-20T00:00:00" and s["ref"] == "probe-suites" and s["body"] == "the long detail"
        d = c.post("/api/fridges/seren-probe/sheets", json={"kind": "list", "title": "done thing", "done": True, "made": "2026-10-01T00:00:00"}).json()
        assert d["place"] == "leftovers" and d["done_at"] == "2026-10-01T00:00:00"


def test_health_and_the_info_route(tmp_path):
    with client(tmp_path) as c:
        h = c.get("/health").json()
        assert h["ok"] and h["service"] == "seren-kitchen" and h["features"] == FEATURES
        r = c.get("/").json()
        assert r["viewer"] == "/viewer" and set(r["updates"]) >= {"status", "distribution", "installed", "latest",
                                                                       "update_available", "detail", "checked_at"}


def test_the_wall_in_one_call(tmp_path):
    with client(tmp_path) as c:
        k = c.get("/api/kitchen").json()
    names = [f["name"] for f in k["fridges"]]
    assert "seren-memory" in names and "seren-kitchen" in names
    assert k["doors"] and k["doors"][0]["fridge"] == "seren-kitchen"        # the housewarming note
    assert k["kinds"][0] == "now" and k["fonts"] == {"name": False, "freezer": False, "hand": False}
    mem = next(f for f in k["fridges"] if f["name"] == "seren-memory")
    assert mem["accent"] == "#ff6e8a" and mem["counts"]["door"] == 0 and mem["held_by"] == []


def test_leave_tick_finish_and_open_the_fridge(tmp_path):
    with client(tmp_path) as c:
        r = c.post("/api/fridges/seren-memory/sheets", json={"kind": "list", "title": "honey-do", "lines": ["a", "b"], "author": "ada"})
        assert r.status_code == 200, r.text
        s = r.json(); assert s["place"] == "shelf" and s["open_lines"] == 2
        f = c.get("/api/fridges/seren-memory").json()
        assert [x["id"] for x in f["shelf"]] == [s["id"]] and f["door"] == [] and f["leftovers"] == []
        s = c.patch(f"/api/sheets/{s['id']}", json={"tick": [0, 1]}).json()
        assert s["place"] == "leftovers" and s["done_at"]
        f = c.get("/api/fridges/seren-memory").json()
        assert [x["id"] for x in f["leftovers"]] == [s["id"]] and f["counts"]["leftovers"] == 1
        assert c.get("/api/sheets", params={"place": "leftovers"}).json()[0]["id"] == s["id"]
        r = c.patch(f"/api/sheets/{s['id']}", json={"colour": "red"})
        assert r.status_code == 400 and "has no colour" in r.text
        assert c.delete(f"/api/sheets/{s['id']}").json()["ok"] and c.get(f"/api/sheets/{s['id']}").status_code == 404


def test_a_refusal_is_a_400_in_plain_words(tmp_path):
    with client(tmp_path) as c:
        r = c.post("/api/fridges/seren-nope/sheets", json={"kind": "now", "title": "x"})
        assert r.status_code == 400 and "no fridge called 'seren-nope'" in r.json()["detail"]
        r = c.post("/api/fridges/seren-memory/sheets", json={"kind": "decision", "title": "pick", "options": ["only one"]})
        assert r.status_code == 400 and "needs choices" in r.json()["detail"]
        r = c.post("/api/fridges/seren-memory/sheets", json={"kind": "person", "title": ""})
        assert r.status_code == 400 and "something to read" in r.json()["detail"]


def test_choices_on_a_line_over_http_and_the_waiting_list(tmp_path):
    with client(tmp_path) as c:
        s = c.post("/api/fridges/seren-probe/sheets", json={"kind": "now", "title": "", "body": "two things", "lines": ["which? a | b", "then rest"]}).json()
        assert s["title"] == "two things" and s["waiting"] is True and s["lines"][0]["options"] == ["a", "b"]
        assert [x["id"] for x in c.get("/api/sheets", params={"waiting": "true"}).json()] == [s["id"]]
        s = c.patch(f"/api/sheets/{s['id']}", json={"pick_line": {"line": 0, "option": "b"}}).json()
        assert s["lines"][0]["pick"] == "b" and s["waiting"] is False
        assert c.get("/api/sheets", params={"waiting": "true"}).json() == []
        assert c.post("/api/fridges/seren-probe/freezer").status_code in (200, 502)   # the dispenser exists; GitHub may not
        assert c.post("/api/fridges/seren-nope/freezer").status_code == 404
        assert c.get("/api/fridges/seren-nope").status_code == 404


def test_decisions_pick_and_sour(tmp_path):
    with client(tmp_path) as c:
        d = c.post("/api/fridges/seren-lyceum/sheets", json={"kind": "decision", "title": "the consolidator", "options": ["a", "b", "c"]}).json()
        assert c.get("/api/sheets", params={"kind": "decision", "open": "true"}).json()[0]["id"] == d["id"]
        d = c.patch(f"/api/sheets/{d['id']}", json={"pick": "b"}).json()
        assert d["pick"] == "b" and d["place"] == "door" and d["done_at"] is None     # picked, not finished: it stays for whoever picks the work up
        assert c.get("/api/sheets", params={"waiting": "true"}).json() == []                # nothing waits on anyone, but the sheet is not done


def test_magnets_over_http(tmp_path):
    with client(tmp_path) as c:
        m = c.post("/api/magnets", json={"partner": "ada", "starter": "start the partner"}).json()
        assert m["fridge"] is None
        m = c.post("/api/magnets/ada/stick", json={"fridge": "seren-soma", "x": 20, "y": 14}).json()
        assert m["fridge"] == "seren-soma"
        f = c.get("/api/fridges/seren-soma").json()
        assert f["held_by"] == ["ada"] and f["magnets"][0]["starter"] == "start the partner"
        k = c.get("/api/kitchen").json()
        assert next(x for x in k["fridges"] if x["name"] == "seren-soma")["held_by"] == ["ada"]
        r = c.post("/api/magnets", json={"partner": "ada", "picture": "http://elsewhere/x.png"})
        assert r.status_code == 400
        assert c.post("/api/magnets/ada/stick", json={"fridge": None}).json()["fridge"] is None
        assert c.delete("/api/magnets/ada").json()["ok"] and c.delete("/api/magnets/ada").status_code == 404


def test_facts_on_the_freezer(tmp_path):
    with client(tmp_path) as c:
        f = c.post("/api/fridges/seren-memory/facts", json={"release": "5.6.1", "build": "ok"}).json()
        assert f["release"] == "5.6.1"
        k = c.get("/api/kitchen").json()
        assert next(x for x in k["fridges"] if x["name"] == "seren-memory")["facts"]["build"] == "ok"


def test_the_bearer_guards_the_api_but_not_the_fonts_or_the_page(tmp_path):
    font = tmp_path / "hand.ttf"; font.write_bytes(b"\0\1\0\0 not really a font")
    with client(tmp_path, bearer="kitchen-secret", fonts=FontsConfig(hand=str(font))) as c:
        assert c.get("/api/kitchen").status_code == 401
        assert c.get("/api/kitchen", headers={"Authorization": "Bearer kitchen-secret"}).status_code == 200
        r = c.get("/api/fonts/hand")
        assert r.status_code == 200 and r.headers["content-type"].startswith("font/ttf")
        assert c.get("/api/fonts/name").status_code == 404 and c.get("/api/fonts/bogus").status_code == 404
        assert c.get("/viewer").status_code == 200 and c.get("/health").status_code == 200


def test_the_page_renders_in_the_shell(tmp_path):
    with client(tmp_path) as c:
        page = c.get("/viewer").text
    assert "Seren<b>Kitchen</b>" in page and ACCENT in page
    for piece in ('id="room"', 'id="cheese"', "Leave a note", "KitchenHand", "/api/fonts/hand"):
        assert piece in page, piece


def test_config_merges_the_yaml_onto_the_family(tmp_path):
    y = tmp_path / "k.yaml"
    y.write_text("fridges:\n  - name: side\n    display: Side\n    accent: '#123456'\n  - name: seren-theatre\n    accent: '#8a3a33'\n"
                 "drop: [seren-carabiner]\nsour_after_days: 3\nfonts:\n  hand: ~/hand.ttf\n", encoding="utf-8")
    cfg = load_config(str(y))
    names = {f["name"]: f for f in cfg.fridges}
    assert "side" in names and names["side"]["accent"] == "#123456" and names["side"]["group"] == "other"
    assert names["seren-theatre"]["accent"] == "#8a3a33" and "seren-carabiner" not in names
    assert cfg.sour_after_days == 3 and cfg.fonts.hand == "~/hand.ttf" and cfg.fonts.path("name") is None
    assert cfg.host == "127.0.0.1" and cfg.port == PORT


def test_the_house_and_each_authors_hand(tmp_path):
    hand = tmp_path / "alex.ttf"; hand.write_bytes(b"\0\1\0\0 pretend")
    from seren_kitchen.config import HouseConfig
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=PORT), state_dir=str(tmp_path / "s"),
                        fonts=FontsConfig(hands={"alex": str(hand), "nobody": str(tmp_path / "missing.ttf")}),
                        house=HouseConfig(person="alex", partner="ada"))
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        k = c.get("/api/kitchen").json()
        assert k["house"]["person"] == "alex" and k["house"]["partner"] == "ada"
        assert k["hands"] == ["alex"]                                       # a hand whose file is missing is not offered
        r = c.get("/api/fonts/hand/alex")
        assert r.status_code == 200 and r.headers["content-type"].startswith("font/ttf")
        assert c.get("/api/fonts/hand/Alex").status_code == 200           # names are matched without case
        assert c.get("/api/fonts/hand/nobody").status_code == 404 and c.get("/api/fonts/hand/ada").status_code == 404
