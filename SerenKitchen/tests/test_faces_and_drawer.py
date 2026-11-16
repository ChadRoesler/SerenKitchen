"""Faces and the drawer (16 Nov 2026). A magnet's face is a file beside the store, not a data URL inside it,
and every face a magnet has worn hangs in a gallery under the fridge it was made for. Magnets nobody is using
go in a drawer under the counter, like the leftovers, so they stop pushing the cheese off the edge."""
from __future__ import annotations

import base64
import json

from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen.app import create_app
from seren_kitchen.config import KitchenConfig
from seren_kitchen.store import Store

PNG = b"\x89PNG\r\n\x1a\n" + b"a face" * 10
PNG2 = b"\x89PNG\r\n\x1a\n" + b"another face" * 10
FRIDGES = [{"name": "seren-kitchen", "display": "Kitchen"}, {"name": "seren-memory", "display": "Memory"}]


def url(data: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(data).decode()


def store(tmp_path) -> Store:
    return Store(tmp_path / "kitchen.json", FRIDGES)


def test_a_face_is_a_file_and_the_json_only_points_at_it(tmp_path):
    st = store(tmp_path)
    m = st.set_magnet("wren", hand="kitchen", picture=url(PNG))
    name = m["picture"].rsplit("/", 1)[-1]
    assert m["picture"].startswith("/api/faces/") and (tmp_path / "faces" / name).read_bytes() == PNG
    raw = (tmp_path / "kitchen.json").read_text(encoding="utf-8")
    assert "base64" not in raw                                                    # the json stays small enough to poll
    # the same picture twice is one file
    st.set_magnet("wren", hand="memory", picture=url(PNG))
    assert len(list((tmp_path / "faces").iterdir())) == 1


def test_the_gallery_keeps_every_face_under_the_fridge_it_was_made_for(tmp_path):
    st = store(tmp_path)
    st.set_magnet("wren", hand="kitchen", picture=url(PNG))                        # on the counter: the hand names the fridge
    st.set_magnet("wren", hand="kitchen", picture=url(PNG2))                       # a new face; the old one stays in the gallery
    faces = st.faces(fridge="seren-kitchen")
    assert len(faces) == 2 and [f["until"] is None for f in faces] == [True, False]
    assert faces[0]["wearing"] == ["wren·kitchen"] and faces[1]["wearing"] == []
    # a hand with no fridge of its own hangs its face on the first fridge it is stuck to
    st.set_magnet("wren", hand="wanderer", picture=url(PNG))
    assert st.faces(fridge="")[0]["label"] == "wren·wanderer"
    st.stick("wren", "seren-memory", hand="wanderer")
    assert st.faces(fridge="") == [] and st.faces(fridge="seren-memory")[0]["label"] == "wren·wanderer"
    # dropping the magnet keeps its faces
    assert st.drop_magnet("wren", "kitchen")
    assert len(st.faces(fridge="seren-kitchen")) == 2


def test_an_old_face_can_be_worn_again_and_a_face_leaves_the_gallery_cleanly(tmp_path):
    st = store(tmp_path)
    first = st.set_magnet("wren", hand="kitchen", picture=url(PNG))["picture"]
    st.set_magnet("wren", hand="kitchen", picture=url(PNG2))
    assert st.set_magnet("wren", hand="kitchen", picture=first)["picture"] == first
    faces = st.faces()
    assert len(faces) == 2                                                        # worn again, not hung twice
    again = next(f for f in faces if f["file"] == first.rsplit("/", 1)[-1])
    assert again["until"] is None and again["wearing"] == ["wren·kitchen"]
    try:
        st.set_magnet("wren", picture="/api/faces/0000000000000000.png")
        raise AssertionError("a face the kitchen does not keep was worn")
    except ValueError as e:
        assert "no face" in str(e)
    # out of the gallery: the file stays while anything still names it
    assert st.drop_face(again["id"]) and st.face_file(again["file"]) is not None  # still worn
    other = next(f for f in st.faces() if f["file"] != again["file"])
    assert st.drop_face(other["id"]) and st.face_file(other["file"]) is None     # nobody wears it, nothing names it


def test_one_face_on_many_magnets_hangs_once_and_old_duplicates_collapse(tmp_path):
    p = tmp_path / "kitchen.json"
    mags = {f"wren·h{i}": {"partner": "wren", "hand": f"h{i}", "label": f"wren·h{i}", "starter": "", "picture": url(PNG),
                           "fridge": None, "x": 1, "y": 2, "since": f"2026-11-0{i + 1}T10:00:00"} for i in range(5)}
    p.write_text(json.dumps({"facts": {}, "sheets": {}, "magnets": mags}), encoding="utf-8")
    (f,) = Store(p, FRIDGES).faces()                                               # five hands, one picture, one place
    assert f["made"] == "2026-11-01T10:00:00" and len(f["wearing"]) == 5
    # a gallery an earlier build hung twice collapses into the first, open if either copy was
    raw = json.loads(p.read_text(encoding="utf-8"))
    dup = {**f, "id": "dup000000000", "made": "2026-11-09T00:00:00", "until": None}
    raw["faces"][f["id"]]["until"] = "2026-11-05T00:00:00"
    raw["faces"]["dup000000000"] = {k: v for k, v in dup.items() if k not in ("url", "wearing")}
    p.write_text(json.dumps(raw), encoding="utf-8")
    (f2,) = Store(p, FRIDGES).faces()
    assert f2["id"] == f["id"] and f2["until"] is None


def test_a_kitchen_from_before_moves_its_faces_out_and_hangs_them(tmp_path):
    p = tmp_path / "kitchen.json"
    p.write_text(json.dumps({"facts": {}, "sheets": {}, "magnets": {"wren": {
        "partner": "wren", "hand": "", "label": "wren", "starter": "", "picture": url(PNG), "fridge": "seren-memory",
        "x": 1, "y": 2, "since": "2026-11-01T10:00:00"}}}), encoding="utf-8")
    st = Store(p, FRIDGES)
    m = st.magnet("wren")
    assert m["picture"].startswith("/api/faces/") and "base64" not in p.read_text(encoding="utf-8")
    (f,) = st.faces()
    assert f["fridge"] == "seren-memory" and f["made"] == "2026-11-01T10:00:00" and f["wearing"] == ["wren"]
    # and a second load does not hang it twice
    assert len(Store(p, FRIDGES).faces()) == 1


def ago(hours: float) -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - hours * 3600))


def test_a_magnets_life_bright_grey_drawer_and_back(tmp_path):
    """Chad, 16 Nov 2026: grey after about twelve hours, the drawer after a few days, and a closed tab is
    enough; nobody has to /exit."""
    st = store(tmp_path)
    st.session_start(partner="wren", session="s1", hand="memory")
    st.stick("wren", "seren-memory", hand="memory")
    mm = st._data["magnets"]["wren·memory"]
    assert st.magnet("wren", "memory")["state"] == "live"
    mm["seen"] = ago(11)
    assert st.magnet("wren", "memory")["state"] == "live"                          # a working afternoon stays bright
    mm["seen"] = ago(13)
    m = st.magnet("wren", "memory")
    assert m["state"] == "idle" and not m["in_drawer"] and m["fridge"] == "seren-memory"   # grey, and still holds it
    assert st.fridges()[1]["held_by"] == ["wren·memory"]
    mm["seen"] = ago(24 * 3 + 1)
    m = st.magnet("wren", "memory")
    assert m["state"] == "missing" and m["in_drawer"] and m["fridge"] == "seren-memory"    # in the drawer, its place kept
    assert st.fridges()[1]["held_by"] == []                                        # and the fridge no longer says so
    # picked up again (context windows are fickle): straight back onto its fridge
    m = st.session_start(partner="wren", session="s2", hand="memory")
    assert m["state"] == "live" and not m["in_drawer"] and m["fridge"] == "seren-memory"
    # an /exit greys it at once, and it stays where it is
    st.session_end(partner="wren", session="s2", reason="logout")
    m = st.magnet("wren", "memory")
    assert m["state"] == "ended" and not m["in_drawer"] and m["fridge"] == "seren-memory"
    # a magnet made by hand, with no session, never ages into the drawer
    st.set_magnet("hand-made")
    assert not st.magnet("hand-made")["in_drawer"]
    # the house sets both numbers
    st.drawer_after = 3600.0
    mm["ended_at"] = ago(2)
    assert st.magnet("wren", "memory")["in_drawer"]


def test_by_hand_in_and_out_of_the_drawer(tmp_path):
    st = store(tmp_path)
    st.session_start(partner="wren", session="s1", hand="memory")
    st.stick("wren", "seren-memory", hand="memory")
    m = st.put_away("wren", True, hand="memory")
    assert m["in_drawer"] and m["fridge"] is None and m["last"] == "seren-memory"
    st._data["magnets"]["wren·memory"]["seen"] = ago(24 * 10)
    assert not st.put_away("wren", False, hand="memory")["in_drawer"]             # out by hand stays out, however old
    st.put_away("wren", True, hand="memory")
    assert not st.session_start(partner="wren", session="s2", hand="memory")["in_drawer"]   # its next session brings it out


def test_a_takeover_moves_the_old_hand_to_the_counter_but_pairing_stays(tmp_path):
    st = store(tmp_path)
    st.session_start(partner="wren", session="s1", hand="kitchen")
    st.stick("wren", "seren-kitchen", hand="kitchen")
    st.stick("chad", "seren-kitchen")                                             # the person of the house beside her: pairing
    st.session_start(partner="wren", session="s2", hand="kitchen-2")
    m = st.stick("wren", "seren-kitchen", hand="kitchen-2")                        # another wren takes the repo
    assert m["fridge"] == "seren-kitchen" and "taken_over_by" not in m
    old = st.magnet("wren", "kitchen")
    assert old["fridge"] is None and old["last"] == "seren-kitchen" and old["taken_over_by"] == "wren·kitchen-2"
    assert not old["in_drawer"] and old["state"] == "live"                        # on the counter, not gone
    assert sorted(st.fridges()[0]["held_by"]) == ["chad", "wren·kitchen-2"]
    # and when the old one sticks somewhere again, the note about being taken over goes
    assert "taken_over_by" not in st.stick("wren", "seren-memory", hand="kitchen")


def test_a_closed_tab_is_taken_over_not_numbered(tmp_path):
    """Busy is not bright: a session quiet for over an hour (a closed tab, most likely) gives its hand to the
    next session in that folder, even though its magnet is still bright for twelve."""
    st = store(tmp_path)
    st.session_start(partner="wren", session="s1", hand="kitchen")
    assert st.session_start(partner="wren", session="s2", hand="kitchen")["label"] == "wren·kitchen-2"   # busy: two seats
    st._data["magnets"]["wren·kitchen"]["seen"] = ago(2)
    m = st.session_start(partner="wren", session="s3", hand="kitchen")
    assert m["label"] == "wren·kitchen" and m["previous"] == "s1" and m["state"] == "live"


def test_a_magnet_remembers_the_sessions_it_carried(tmp_path):
    st = store(tmp_path)
    st.set_magnet("wren", hand="kitchen", picture=url(PNG))
    st.session_start(partner="wren", session="s1", hand="kitchen", cwd="D:/k")
    st.session_end(partner="wren", session="s1", reason="logout")
    m = st.session_start(partner="wren", session="s2", hand="kitchen", cwd="D:/k")
    (h,) = m["history"]
    assert h["session"] == "s1" and h["end_reason"] == "logout" and "s1" in h["starter"] and h["picture"].startswith("/api/faces/")
    for n in range(3, 20):
        st.session_end(partner="wren", session=f"s{n - 1}", reason="logout")       # a live one would be a new hand, kitchen-2
        st.session_start(partner="wren", session=f"s{n}", hand="kitchen")
    assert len(st.magnet("wren", "kitchen")["history"]) == 12


def test_faces_gallery_and_drawer_over_http(tmp_path):
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431, bearer_token="tok"), state_dir=str(tmp_path / "s"))
    auth = {"Authorization": "Bearer tok"}
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        m = c.post("/api/magnets", json={"partner": "wren", "hand": "kitchen", "picture": url(PNG)}, headers=auth).json()
        r = c.get(m["picture"])                                                     # public: an <img> sends no bearer
        assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
        assert c.get("/api/faces/kitchen.json").status_code == 404                   # only a face's own name
        assert c.get("/api/gallery").status_code == 401                              # the listing is not public
        g = c.get("/api/gallery", params={"fridge": "seren-kitchen"}, headers=auth).json()
        assert [f["label"] for f in g] == ["wren·kitchen"]
        assert c.get("/api/fridges/seren-kitchen", headers=auth).json()["faces"][0]["id"] == g[0]["id"]
        d = c.post("/api/magnets/wren/drawer", json={"hand": "kitchen", "away": True}, headers=auth).json()
        assert d["in_drawer"] is True
        assert c.post("/api/magnets/wren/drawer", json={"hand": "nope"}, headers=auth).status_code == 400
        assert c.delete(f"/api/gallery/{g[0]['id']}", headers=auth).json() == {"ok": True}
        assert c.delete(f"/api/gallery/{g[0]['id']}", headers=auth).status_code == 404
        assert c.post("/api/magnets", json={"partner": "wren", "picture": "data:image/png;base64,bm90IGEgcGljdHVyZQ=="},
                      headers=auth).status_code == 400                                # labelled png, is not


def test_stick_on_start_takes_the_repo_and_says_who_had_it(tmp_path):
    st = Store(tmp_path / "kitchen.json", [{"name": "seren-kitchen", "display": "Kitchen", "repo": "me/SerenKitchen"},
                                           {"name": "seren-memory", "display": "Memory"}])
    a = st.session_start(partner="wren", session="s1", cwd="D:/x/SerenKitchen")
    assert a["fridge"] == "seren-kitchen" and a["took_from"] == []
    b = st.session_start(partner="wren", session="s2", cwd="D:/x/SerenKitchen")                # s1 is busy: s2 is kitchen-2
    assert b["label"] == "wren·kitchen-2" and b["fridge"] == "seren-kitchen"
    assert b["took_from"] == [{"label": "wren·kitchen", "state": "live", "busy": True}]
    assert st.magnet("wren", "kitchen")["fridge"] is None                                    # on the counter, told on its next prompt
    # a folder that is no fridge's repo holds nothing; and the house can turn it off
    assert st.session_start(partner="wren", session="s3", cwd="D:/x/notes")["fridge"] is None
    st.stick_on_start = False
    st.stick("wren", None, hand="kitchen-2")
    st._data["magnets"]["wren·kitchen-2"]["seen"] = ago(2)
    assert st.session_start(partner="wren", session="s4", cwd="D:/x/SerenKitchen", hand="kitchen-2")["fridge"] is None


def test_a_touch_keeps_a_session_bright_and_tells_it_once_when_it_was_taken_over(tmp_path):
    st = store(tmp_path)
    st.session_start(partner="wren", session="s1", hand="kitchen")
    st.stick("wren", "seren-kitchen", hand="kitchen")
    st._data["magnets"]["wren·kitchen"]["seen"] = ago(30)
    m, note = st.touch(partner="wren", session="s1")
    assert m["state"] == "live" and note == ""                                               # a prompt is a sign of life
    # another hand takes the fridge: the old one learns it on its next prompt, and only once
    st.session_start(partner="wren", session="s2", hand="kitchen-2")
    st.stick("wren", "seren-kitchen", hand="kitchen-2")
    m, note = st.touch(partner="wren", session="s1")
    assert "wren·kitchen-2 took seren-kitchen" in note and "still at work there" in note and m["fridge"] is None
    assert st.touch(partner="wren", session="s1")[1] == ""
    # a newer session takes the hand itself while s3 is quiet: s3 learns it, once
    st.session_start(partner="wren", session="s3", hand="memory")
    st._data["magnets"]["wren·memory"]["seen"] = ago(2)
    st.session_start(partner="wren", session="s4", hand="memory")
    m, note = st.touch(partner="wren", session="s3")
    assert "taken over by a newer session (s4)" in note
    assert st.touch(partner="wren", session="s3")[1] == ""
    assert st.touch(partner="wren", session="never-heard-of-it") == (None, "")


def test_touch_over_http_and_the_magnet_life_settings(tmp_path):
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "s"))
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        c.post("/api/sessions", json={"event": "start", "partner": "wren", "session": "s1", "hand": "kitchen"})
        r = c.post("/api/sessions", json={"event": "touch", "partner": "wren", "session": "s1"})
        assert r.status_code == 200 and r.json()["say"] == "" and r.json()["state"] == "live"
        assert c.post("/api/sessions", json={"event": "touch", "partner": "wren", "session": "nope"}).status_code == 404
        assert c.get("/api/kitchen").json()["magnet_life"] == {"grey_after_hours": 12.0, "drawer_after_days": 3.0, "stick_on_start": True}
        life = c.post("/api/settings/magnets", json={"grey_after_hours": 6, "drawer_after_days": 7, "stick_on_start": False}).json()
        assert life == {"grey_after_hours": 6.0, "drawer_after_days": 7.0, "stick_on_start": False}
    with TestClient(create_app(cfg, run_freezer=False)) as c:                                # kept across a restart
        assert c.get("/api/kitchen").json()["magnet_life"]["stick_on_start"] is False


def test_the_yaml_gives_a_new_kitchen_its_magnet_life(tmp_path):
    from seren_kitchen.config import load_config
    y = tmp_path / "k.yaml"
    y.write_text(f"state_dir: {str(tmp_path / 's').replace(chr(92), '/')}\nmagnets:\n  grey_after_hours: 2\n  drawer_after_days: 14\n  stick_on_start: false\n",
                 encoding="utf-8")
    cfg = load_config(str(y))
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        assert c.get("/api/kitchen").json()["magnet_life"] == {"grey_after_hours": 2.0, "drawer_after_days": 14.0, "stick_on_start": False}
