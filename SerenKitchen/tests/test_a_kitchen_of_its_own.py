"""A kitchen ships knowing no repos. The wall is the house's own fridge and whatever the yaml lists or the page
adds; the house fridge is named by the house; a hand leaves off a prefix only when the house says its fridges
share one. And a kitchen whose yaml lost its fridges keeps every sheet for when they come back."""
from __future__ import annotations

from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen.app import create_app
from seren_kitchen.config import HouseConfig, KitchenConfig, MagnetsConfig, load_config
from seren_kitchen.store import HOUSEWARMING, Store

ACME = [{"name": "acme-billing", "display": "Billing", "repo": "acme/AcmeBilling"},
        {"name": "acme-ledger", "display": "Ledger", "repo": "acme/AcmeLedger"}]


def config(tmp_path, **kw) -> KitchenConfig:
    return KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "s"), **kw)


def test_a_bare_kitchen_is_one_fridge_with_a_note_on_it(tmp_path):
    with TestClient(create_app(config(tmp_path), run_freezer=False)) as c:
        k = c.get("/api/kitchen").json()
        assert [f["name"] for f in k["fridges"]] == ["house"] and k["house"]["fridge"] == "house"
        assert [(s["fridge"], s["title"]) for s in k["doors"]] == [("house", HOUSEWARMING["title"])]
        # the page adds the rest
        assert c.post("/api/settings/fridges", json={"name": "acme-billing", "repo": "acme/AcmeBilling"}).status_code == 200
        assert [f["name"] for f in c.get("/api/kitchen").json()["fridges"]] == ["acme-billing", "house"]      # the house is drawn as the big fridge, wherever it sits


def test_the_house_names_its_own_fridge_and_it_cannot_be_lost(tmp_path):
    cfg = config(tmp_path, fridges=ACME, house=HouseConfig(fridge="home"))
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        k = c.get("/api/kitchen").json()
        assert [f["name"] for f in k["fridges"]] == ["acme-billing", "acme-ledger", "home"] and k["house"]["fridge"] == "home"
        assert k["doors"][0]["fridge"] == "home"
        c.patch("/api/settings/fridges/home", json={"hidden": True})            # hidden from the page: the big fridge stays
        assert "home" in [f["name"] for f in c.get("/api/kitchen").json()["fridges"]]
        assert c.post("/api/fridges/home/sheets", json={"title": "still here"}).status_code == 200


def test_a_hand_keeps_the_whole_fridge_name_unless_the_house_shares_a_prefix(tmp_path):
    plain = Store(tmp_path / "a.json", ACME)
    m = plain.session_start(partner="ada", session="s-1", cwd="/work/AcmeBilling")
    assert m["hand"] == "acme-billing" and m["fridge"] == "acme-billing"
    trimmed = Store(tmp_path / "b.json", ACME, trim_prefix="acme-")
    m = trimmed.session_start(partner="ada", session="s-1", cwd="D:\\work\\AcmeBilling")
    assert m["hand"] == "billing" and m["label"] == "ada·billing" and m["fridge"] == "acme-billing"
    assert trimmed.hand_for("/work/Elsewhere") == "elsewhere"                   # no fridge's repo: the folder's name
    # a face hangs under the fridge its hand is named after, either way the hand was made
    for st, hand in ((plain, "acme-ledger"), (trimmed, "ledger")):
        st.set_magnet("bea", hand=hand, picture="data:image/png;base64,iVBORw0KGgo=")
        assert [f["fridge"] for f in st.faces() if f["label"] == f"bea·{hand}"] == ["acme-ledger"]


def test_the_yaml(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("house:\n  fridge: Home\nmagnets:\n  trim_prefix: ' ACME- '\n"
                 "fridges:\n  - name: acme-billing\n    repo: acme/AcmeBilling\n  - name: Not A Slug\n  - name: acme-billing\n    display: Billing\n",
                 encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.house.fridge == "home" and cfg.magnets.trim_prefix == "acme-"
    assert cfg.fridges == [{"name": "acme-billing", "display": "Billing", "group": "other", "accent": "#cccccc", "repo": "acme/AcmeBilling"}]
    p.write_text("house:\n  fridge: 'no good!'\n", encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.house.fridge == "house" and cfg.fridges == [] and cfg.magnets.trim_prefix == ""
    assert KitchenConfig().fridges == []                                          # nothing ships on the wall


def test_sheets_for_a_fridge_that_left_the_wall_wait_for_it(tmp_path):
    """The upgrade that took the family's fridges out of the package: a kitchen.json full of them, a yaml that
    has not been told yet. Nothing is lost, the settings say what waits, and the yaml brings it all back."""
    old = [{"name": "seren-project", "display": "The House"}, {"name": "seren-memory", "display": "Memory"}]
    st = Store(tmp_path / "s" / "kitchen.json", old)
    st.leave(fridge="seren-project", kind="person", title="on the big fridge", author="alex")
    st.leave(fridge="seren-memory", kind="list", title="a list", lines=["x"], author="ada")
    with TestClient(create_app(config(tmp_path), run_freezer=False)) as c:
        assert [f["name"] for f in c.get("/api/kitchen").json()["fridges"]] == ["house"]
        assert c.get("/api/settings").json()["off_the_wall"] == {"seren-memory": 1, "seren-project": 1}
        assert not c.get("/api/kitchen").json()["doors"]                           # no second housewarming in a lived-in kitchen
    back = config(tmp_path, fridges=[{"name": "seren-memory", "display": "Memory"}], house=HouseConfig(fridge="seren-project"))
    with TestClient(create_app(back, run_freezer=False)) as c:
        k = c.get("/api/kitchen").json()
        assert k["house"]["fridge"] == "seren-project" and [s["title"] for s in k["doors"]] == ["on the big fridge"]
        assert [s["title"] for s in c.get("/api/fridges/seren-memory").json()["shelf"]] == ["a list"]
        assert c.get("/api/settings").json()["off_the_wall"] == {}
