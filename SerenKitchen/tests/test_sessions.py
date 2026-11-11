"""Sessions on magnets: a start makes or takes over the hand's magnet with a starter built from the folder
and the id, the hand is read off the folder when none is given, a second live session under the same hand
is the next number, an end marks the magnet ended, and the page is told a state."""
from __future__ import annotations

from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen.app import create_app
from seren_kitchen.config import KitchenConfig
from seren_kitchen.store import Store

FRIDGES = [{"name": "seren-memory", "display": "Memory", "repo": "someone/SerenMemory"},
           {"name": "seren-carabiner", "display": "Carabiner", "repo": "someone/SerenCarabiners"},
           {"name": "seren-project", "display": "The House"}]


def test_a_start_takes_the_hands_magnet_and_an_end_marks_it(tmp_path):
    st = Store(tmp_path / "k.json", FRIDGES, sour_after_days=7)
    m = st.session_start(partner="ada", session="aaaa-1", cwd="D:\\work\\SerenCarabiners", box="desk", source="startup")
    assert m["hand"] == "carabiner" and m["label"] == "ada·carabiner"                 # read off the folder, against the fridge's repo
    assert m["starter"] == "cd D:\\work\\SerenCarabiners\nclaude --resume aaaa-1" and m["state"] == "live" and m["fridge"] is None
    assert st.session_end(partner="ada", session="nope") is None
    m = st.session_end(partner="ada", session="aaaa-1", reason="prompt_input_exit")          # the context flooded; the hook said so
    assert m["state"] == "ended" and m["end_reason"] == "prompt_input_exit" and m["label"] == "ada·carabiner"
    m = st.session_start(partner="ada", session="aaaa-2", cwd="D:\\work\\SerenCarabiners", source="startup", hand="carabiner")
    assert m["session"] == "aaaa-2" and m["previous"] == "aaaa-1" and len(st.magnets()) == 1   # a takeover, not a second magnet
    assert m["state"] == "live" and m["ended_at"] is None


def test_two_live_sessions_in_one_folder_are_numbered(tmp_path):
    st = Store(tmp_path / "k.json", FRIDGES)
    st.session_start(partner="ada", session="one", cwd="/home/x/SerenMemory")
    m = st.session_start(partner="ada", session="two", cwd="/home/x/SerenMemory")
    assert m["hand"] == "memory-2" and {x["label"] for x in st.magnets()} == {"ada·memory", "ada·memory-2"}
    assert st.session_start(partner="ada", session="two", cwd="/home/x/SerenMemory")["hand"] == "memory-2"   # itself again, not a third
    assert st.hand_for("/somewhere/Elsewhere Repo") == "elsewhere-repo" and st.hand_for("") == ""


def test_the_hook_route_and_the_state_on_the_wall(tmp_path):
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "s"))
    with TestClient(create_app(cfg, run_freezer=False)) as c:
        r = c.post("/api/sessions", json={"event": "start", "partner": "ada", "harness": "claude", "session": "s-1",
                                          "cwd": "C:\\git\\SerenMemory", "box": "desk", "source": "startup"})
        j = r.json(); say = j.pop("say")
        assert r.status_code == 200 and j == {"ok": True, "label": "ada·memory", "hand": "memory", "on": None, "state": "live",
                                              "starter": "cd C:\\git\\SerenMemory\nclaude --resume s-1"}
        assert say.startswith("The kitchen knows this session as ada·memory.") and 'hand="memory"' in say and "on the counter" in say
        r2 = c.post("/api/sessions", json={"event": "start", "partner": "ada", "session": "s-2", "cwd": "C:\\git\\SerenMemory"})
        assert r2.json()["hand"] == "memory-2" and r2.json()["say"].startswith("Another live session of ada holds memory; the kitchen knows this one as ada·memory-2.")
        c.post("/api/magnets/ada/stick", json={"fridge": "seren-memory", "hand": "memory"})
        m = c.get("/api/kitchen").json()["magnets"][0]
        assert m["state"] == "live" and m["session"] == "s-1" and m["fridge"] == "seren-memory"
        r = c.post("/api/sessions", json={"event": "end", "partner": "ada", "session": "s-1", "reason": "clear"})
        assert r.json()["state"] == "ended" and r.json()["on"] == "seren-memory"               # it stays where it was
        assert r.json()["say"] == "The kitchen marked ada·memory ended (clear). The magnet stays where it was."
        assert c.post("/api/sessions", json={"event": "end", "partner": "ada", "session": "ghost"}).status_code == 404
        assert c.post("/api/sessions", json={"event": "poke"}).status_code == 400
        assert c.post("/api/sessions", json={"event": "start", "partner": "", "session": "x"}).status_code == 400
        # a magnet made by hand, with no session, has no state
        c.post("/api/magnets", json={"partner": "ada", "hand": "kitchen"})
        assert next(x for x in c.get("/api/magnets").json() if x["hand"] == "kitchen")["state"] == ""
