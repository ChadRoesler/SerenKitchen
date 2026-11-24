"""What the house decides after moving in, from the page: fonts uploaded and served, a GitHub token kept as a
600 file and never read back, fridges added, recoloured, hidden and reordered, the house's names, the milk."""
from __future__ import annotations

from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from conftest import WALL
from seren_kitchen.app import create_app
from seren_kitchen.config import KitchenConfig

TTF = b"\x00\x01\x00\x00" + b"\x00" * 60     # the first four bytes of a TrueType file are what the kitchen checks


def client(tmp_path):
    cfg = KitchenConfig(fridges=WALL, server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "s"))
    return TestClient(create_app(cfg, run_freezer=False))


def test_fonts_uploaded_from_the_page_are_served_and_beat_the_yaml(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/api/fonts/hand").status_code == 404
        r = c.post("/api/settings/fonts/hand", content=TTF, headers={"Content-Type": "font/ttf"})
        assert r.status_code == 200 and r.json()["file"] == "hand.ttf"
        assert (tmp_path / "s" / "fonts" / "hand.ttf").read_bytes() == TTF
        got = c.get("/api/fonts/hand")
        assert got.status_code == 200 and got.content == TTF
        assert c.get("/api/kitchen").json()["fonts"]["hand"] is True
        # a hand for an author, matched without case, listed on the wall, gone when dropped
        r = c.post("/api/settings/fonts/hand/Alex", content=TTF, headers={"Content-Type": "font/ttf"})
        assert r.json() == {"author": "alex", "file": "hand-alex.ttf"}
        assert c.get("/api/fonts/hand/alex").status_code == 200 and c.get("/api/kitchen").json()["hands"] == ["alex"]
        assert c.delete("/api/settings/fonts/hand/alex").json()["ok"] and c.get("/api/fonts/hand/alex").status_code == 404
        # not a font
        assert c.post("/api/settings/fonts/name", content=b"hello", headers={"Content-Type": "font/ttf"}).status_code == 400
        assert c.post("/api/settings/fonts/elbow", content=TTF, headers={"Content-Type": "font/ttf"}).status_code == 400
        assert c.delete("/api/settings/fonts/name").status_code == 404


def test_the_github_token_is_a_file_that_never_comes_back_out(tmp_path):
    with client(tmp_path) as c:
        assert c.get("/api/settings").json()["github"]["token_set"] is False
        r = c.post("/api/settings/github", json={"token": "ghp_" + "a" * 36, "interval_minutes": 7})
        assert r.status_code == 200 and r.json()["token_set"] is True and r.json()["interval_minutes"] == 7
        p = tmp_path / "s" / "github_token"
        assert p.read_text().strip() == "ghp_" + "a" * 36
        import json
        assert "ghp_" not in json.dumps(c.get("/api/settings").json())          # the view never carries it
        assert "ghp_" not in (tmp_path / "s" / "settings.json").read_text()      # nor does settings.json
        assert c.post("/api/settings/github", json={"token": "nope"}).status_code == 400
        assert c.post("/api/settings/github", json={"token": ""}).json()["token_set"] is False
        assert not p.exists()


def test_fridges_added_recoloured_hidden_and_reordered(tmp_path):
    with client(tmp_path) as c:
        r = c.post("/api/settings/fridges", json={"name": "side", "display": "Side", "accent": "#123456", "repo": "me/side"})
        assert r.status_code == 200, r.text
        names = [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]
        assert "side" in names
        s = c.post("/api/fridges/side/sheets", json={"kind": "now", "title": "on the new fridge"}).json()
        assert s["fridge"] == "side"
        r = c.patch("/api/settings/fridges/seren-theatre", json={"accent": "#8a3a33", "display": "The Theatre"})
        assert r.json()["overrides"] == {"accent": "#8a3a33", "display": "The Theatre"}
        th = next(f for f in c.get("/api/kitchen").json()["fridges"] if f["name"] == "seren-theatre")
        assert th["accent"] == "#8a3a33" and th["display"] == "The Theatre"
        assert c.patch("/api/settings/fridges/seren-carabiner", json={"hidden": True}).json()["hidden"] is True
        assert "seren-carabiner" not in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]
        c.patch("/api/settings/fridges/seren-carabiner", json={"hidden": False})
        assert "seren-carabiner" in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]
        order = c.post("/api/settings/order", json={"order": ["side", "seren-kitchen"]}).json()["order"]
        assert order[:2] == ["side", "seren-kitchen"]
        assert c.patch("/api/settings/fridges/seren-nope", json={"accent": "#000000"}).status_code == 404
        assert c.post("/api/settings/fridges", json={"name": "Bad Name!", "accent": "#123456"}).status_code == 400
        assert c.post("/api/settings/fridges", json={"name": "ok", "accent": "red"}).status_code == 400
    # and it all comes back after a restart
    with client(tmp_path) as c:
        k = c.get("/api/kitchen").json()
        assert [f["name"] for f in k["fridges"]][:2] == ["side", "seren-kitchen"]
        assert next(f for f in k["fridges"] if f["name"] == "seren-theatre")["accent"] == "#8a3a33"


def test_the_house_and_the_milk(tmp_path):
    with client(tmp_path) as c:
        assert c.post("/api/settings/house", json={"person": "alex", "partner": "ada"}).json() == {"person": "alex", "partner": "ada"}
        h = c.get("/api/kitchen").json()["house"]
        assert h["person"] == "alex" and h["partner"] == "ada" and h["notes_at"] == "top" and h["hinge"] == "right" and h["fridge"] == "house"
        assert c.post("/api/settings/house", json={"notes_at": "bottom", "hinge": "left"}).status_code == 200
        h = c.get("/api/kitchen").json()["house"]
        assert h["notes_at"] == "bottom" and h["hinge"] == "left"
        assert c.post("/api/settings/house", json={"hinge": "upside-down"}).status_code == 400
        assert "house" in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]   # every kitchen has a House
        assert c.post("/api/settings/sour", json={"days": 3}).json()["sour_after_days"] == 3
        assert c.get("/api/kitchen").json()["sour_after_days"] == 3
        assert c.post("/api/settings/sour", json={"days": "soon"}).status_code == 400
        assert "settings" in c.get("/health").json()["features"]


def test_a_settings_file_in_the_wrong_shape_is_refused_in_part_not_whole(tmp_path):
    """settings.json is the page's own, but it is a file a person can open. A section in the wrong shape (the
    fridges' settings pasted as a list of fridges) is left out with a word, the rest is read, the file as it was
    is kept beside it, and the kitchen starts."""
    import json
    st = tmp_path / "s"
    st.mkdir()
    (st / "settings.json").write_text(json.dumps({
        "house": {"person": "alex", "partner": "ada"},
        "fridges": [{"name": "my-app", "repo": "me/MyApp"}],
        "fonts": {"hands": ["not", "a", "mapping"]}}), encoding="utf-8")
    with client(tmp_path) as c:
        assert c.get("/health").json()["ok"]
        h = c.get("/api/kitchen").json()["house"]
        assert h["person"] == "alex" and h["partner"] == "ada"                          # the good part was read
        refused = c.get("/api/settings").json()["refused"]
        assert any("'fridges' is a list" in r for r in refused) and any("fonts.hands is a list" in r for r in refused)
        kept = list(st.glob("settings.json.refused-*"))
        assert len(kept) == 1 and json.loads(kept[0].read_text(encoding="utf-8"))["fridges"][0]["name"] == "my-app"
        # the page works on, and writing the file whole does not lose what was set aside
        assert c.post("/api/settings/fridges", json={"name": "my-app", "repo": "me/MyApp"}).status_code == 200
        assert "my-app" in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]
    with client(tmp_path) as c:                                                         # and the next start is clean
        assert "refused" not in c.get("/api/settings").json()


def test_a_settings_file_that_is_not_json_or_has_a_bad_fridge_starts_anyway(tmp_path):
    import json
    st = tmp_path / "s"
    st.mkdir()
    (st / "settings.json").write_text("{ fridges: oops", encoding="utf-8")
    with client(tmp_path) as c:
        assert c.get("/health").json()["ok"] and "not JSON" in c.get("/api/settings").json()["refused"][0]
    assert (st / "settings.json").read_text(encoding="utf-8") == "{ fridges: oops"     # untouched until the page writes
    (st / "settings.json").write_text(json.dumps({"fridges": {"extra": ["my-app", {"name": "ok-app"}]}}), encoding="utf-8")
    with client(tmp_path) as c:
        assert [f for f in c.get("/api/kitchen").json()["fridges"] if f["name"] == "ok-app"]
        assert "1 of fridges.extra are not a fridge" in c.get("/api/settings").json()["refused"][0]


def test_a_fridge_added_from_the_page_can_be_removed_and_its_sheets_go_where_the_house_says(tmp_path):
    with client(tmp_path) as c:
        for name in ("side", "scratch"):
            assert c.post("/api/settings/fridges", json={"name": name, "repo": f"me/{name}"}).status_code == 200
        c.patch("/api/settings/fridges/side", json={"display": "Side", "hidden": False})
        a = c.post("/api/fridges/side/sheets", json={"title": "keep me", "author": "alex"}).json()
        c.post(f"/api/sheets/{a['id']}/reply", json={"body": "me too", "author": "ada"})
        c.post("/api/magnets/ada/stick", json={"fridge": "side", "hand": "side"})
        c.post("/api/fridges/scratch/sheets", json={"title": "left behind", "author": "alex"})
        # moved: the sheet and the note stuck on it go to the other fridge; the magnet goes back on the counter
        r = c.delete("/api/settings/fridges/side", params={"move_to": "seren-memory"}).json()
        assert r == {"removed": "side", "sheets_moved": 2, "to": "seren-memory", "sheets_kept": 0, "magnets_set_down": ["ada·side"]}
        assert "side" not in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]
        assert c.get(f"/api/sheets/{a['id']}").json()["fridge"] == "seren-memory" and len(c.get(f"/api/sheets/{a['id']}").json()["replies"]) == 1
        m = next(m for m in c.get("/api/magnets").json() if m["label"] == "ada·side")
        assert m["fridge"] is None and m["last"] == "side"
        s = c.get("/api/settings").json()["fridges"]
        assert "side" not in s["overrides"] and not [x for x in s["extra"] if x["name"] == "side"]   # one added again starts fresh
        # kept: off the wall, counted, and movable later
        assert c.delete("/api/settings/fridges/scratch").json()["sheets_kept"] == 1
        assert c.get("/api/settings").json()["off_the_wall"] == {"scratch": 1}
        assert c.post("/api/fridges/scratch/move", json={"to": "house"}).json() == {"from": "scratch", "to": "house", "moved": 1}
        assert c.get("/api/settings").json()["off_the_wall"] == {}


def test_what_cannot_be_removed_says_why(tmp_path):
    with client(tmp_path) as c:
        c.post("/api/settings/fridges", json={"name": "side"})
        assert "house's own fridge stays" in c.delete("/api/settings/fridges/house").json()["detail"]
        assert "is in the yaml" in c.delete("/api/settings/fridges/seren-memory").json()["detail"]
        assert c.delete("/api/settings/fridges/nope").status_code == 404
        assert c.delete("/api/settings/fridges/side", params={"move_to": "side"}).status_code == 400
        assert c.delete("/api/settings/fridges/side", params={"move_to": "nope"}).status_code == 400
        assert "side" in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]      # a refused removal removed nothing
        assert c.post("/api/fridges/nope/move", json={"to": "house"}).status_code == 404
        c.post("/api/fridges/side/sheets", json={"title": "x"})
        assert c.post("/api/fridges/side/move", json={"to": "nope"}).status_code == 400
        assert c.post("/api/fridges/side/move", json={"to": "side"}).status_code == 400
