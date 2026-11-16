"""The kitchen backs itself up like every other store in the family (seren_sinew.stores): what it keeps is
declared at GET /stores, a snapshot is one call, a rehearsal proves one can be put back, and a restore is two
yaml keys and a restart, into an empty kitchen only. The GitHub token is never in a snapshot."""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen.app import create_app
from seren_kitchen.config import BackupConfig, KitchenConfig, load_config

PNG = b"\x89PNG\r\n\x1a\n" + b"a face" * 10
TOKEN = "ghp_" + "x" * 36


def cfg_at(tmp_path, **backup) -> KitchenConfig:
    return KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "home" / "state"),
                         backup=BackupConfig(every_hours=0, **backup))


def fill(c: TestClient) -> str:
    s = c.post("/api/fridges/seren-kitchen/sheets", json={"kind": "art", "title": "macaroni"}).json()
    assert c.post(f"/api/sheets/{s['id']}/art", content=PNG, headers={"Content-Type": "image/png"}).status_code == 200
    c.post("/api/magnets", json={"partner": "wren", "hand": "kitchen", "picture": "data:image/png;base64," + base64.b64encode(PNG).decode()})
    assert c.post("/api/settings/github", json={"token": TOKEN}).status_code == 200
    return s["id"]


def test_a_snapshot_holds_the_kitchen_its_pictures_and_faces_but_never_the_token(tmp_path):
    with TestClient(create_app(cfg_at(tmp_path), run_freezer=False)) as c:
        fill(c)
        d = c.get("/stores").json()
        assert {s["name"] for s in d["stores"]} == {"kitchen", "settings", "art", "faces", "fonts"}
        assert Path(d["snapshots"]["dir"]) == tmp_path / "home" / "backups" / "seren-kitchen"     # beside the state, not in it
        snap = c.post("/stores/snapshot", json={"reason": "by hand"}).json()["snapshot"]
        assert snap["counts"] == {"sheets": 2, "magnets": 1, "faces": 1}                          # the housewarming note, and ours
        root = Path(snap["path"])
        files = [p.name for p in root.rglob("*") if p.is_file()]
        assert "kitchen.json" in files and "settings.json" in files and any(f.endswith(".png") for f in files)
        assert "github_token" not in files and TOKEN not in "".join(p.read_text(errors="ignore") for p in root.rglob("*") if p.is_file())
        rep = c.post(f"/stores/snapshots/{snap['id']}/rehearse").json()
        assert rep["ok"] is True, rep["problems"]
        assert c.get(f"/stores/snapshots/{snap['id']}/archive").status_code == 200                # a Lodestar may carry it


def test_a_rehearsal_notices_a_face_that_is_missing(tmp_path):
    with TestClient(create_app(cfg_at(tmp_path), run_freezer=False)) as c:
        fill(c)
        for f in (tmp_path / "home" / "state" / "faces").iterdir():
            f.unlink()
        snap = c.post("/stores/snapshot").json()["snapshot"]
        rep = c.post(f"/stores/snapshots/{snap['id']}/rehearse").json()
        assert rep["ok"] is False and any("face" in p for p in rep["problems"])


def test_pull_can_be_kept_on_the_box_and_backups_switched_off(tmp_path):
    with TestClient(create_app(cfg_at(tmp_path, allow_pull=False), run_freezer=False)) as c:
        sid = c.post("/stores/snapshot").json()["snapshot"]["id"]
        assert c.get(f"/stores/snapshots/{sid}/archive").status_code == 403
    with TestClient(create_app(cfg_at(tmp_path / "off", enabled=False), run_freezer=False)) as c:
        assert c.get("/stores").status_code == 404                                                # a Lodestar skips it


def test_a_restore_puts_a_kitchen_back_into_an_empty_one_only(tmp_path):
    with TestClient(create_app(cfg_at(tmp_path), run_freezer=False)) as c:
        sid = fill(c)
        snap = Path(c.post("/stores/snapshot").json()["snapshot"]["path"])
    fresh = cfg_at(tmp_path / "new", restore_from=str(snap), restore_reason="the old box died")
    with TestClient(create_app(fresh, run_freezer=False)) as c:
        assert c.get(f"/api/sheets/{sid}").json()["title"] == "macaroni"
        art = c.get(f"/api/sheets/{sid}").json()["art"][0]
        assert c.get(f"/api/art/{art}").content == PNG
        m = c.get("/api/magnets").json()[0]
        assert c.get(m["picture"]).content == PNG
    # a second start with the key still set passes it by: the kitchen is no longer empty
    with TestClient(create_app(fresh, run_freezer=False)) as c:
        assert c.get(f"/api/sheets/{sid}").status_code == 200
    with pytest.raises(Exception):
        with TestClient(create_app(cfg_at(tmp_path / "x", restore_from=str(snap)), run_freezer=False)):
            pass                                                                                  # no reason: refused


def test_the_yaml_backup_block(tmp_path):
    y = tmp_path / "k.yaml"
    y.write_text("state_dir: ~/k/state\nbackup:\n  every_hours: 6\n  allow_pull: false\n  dir: /tmp/kb\n  compress: zip\n", encoding="utf-8")
    cfg = load_config(str(y))
    assert cfg.backup.every_hours == 6 and cfg.backup.allow_pull is False and cfg.backup.compress == "gz"
    assert cfg.backup_path == Path("/tmp/kb")
    assert load_config(str(tmp_path / "missing.yaml")).backup.enabled is True
