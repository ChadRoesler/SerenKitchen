"""Pictures on sheets: the body is the picture, it is kept beside the store, served without a bearer,
replaced by a new one, refused when it is the wrong thing or too big, and taken down with its sheet."""
from __future__ import annotations

import struct
import zlib

from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen.app import MAX_ART, create_app
from seren_kitchen.config import KitchenConfig


def png(w=2, h=2, colour=(220, 160, 60)) -> bytes:
    """A real little PNG (macaroni-coloured), so nothing downstream has to fake a header."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(colour) * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def client(tmp_path, bearer=""):
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431, bearer_token=bearer), state_dir=str(tmp_path / "s"))
    return TestClient(create_app(cfg, run_freezer=False))


def test_macaroni_goes_in_the_crisper(tmp_path):
    with client(tmp_path, bearer="k") as c:
        auth = {"Authorization": "Bearer k"}
        s = c.post("/api/fridges/seren-kitchen/sheets", json={"kind": "art", "title": "macaroni cat", "author": "alex"}, headers=auth).json()
        assert s["place"] == "crisper" and s["art"] == []
        r = c.post(f"/api/sheets/{s['id']}/art", content=png(), headers={**auth, "Content-Type": "image/png"})
        assert r.status_code == 200, r.text
        first = f"{s['id']}-0.png"
        assert r.json()["art"] == [first]
        assert (tmp_path / "s" / "art" / first).read_bytes() == png()
        img = c.get(f"/api/art/{first}")                                         # no bearer: an <img> cannot send one
        assert img.status_code == 200 and img.headers["content-type"] == "image/png" and img.content == png()
        f = c.get("/api/fridges/seren-kitchen", headers=auth).json()
        assert f["crisper"][0]["art"] == [first]
        # a second picture joins the gallery; ?replace=true starts over
        r = c.post(f"/api/sheets/{s['id']}/art", content=b"GIF89a-ish", headers={**auth, "Content-Type": "image/gif"})
        assert r.json()["art"] == [first, f"{s['id']}-1.gif"]
        r = c.delete(f"/api/sheets/{s['id']}/art/{first}", headers=auth)
        assert r.json()["art"] == [f"{s['id']}-1.gif"] and c.get(f"/api/art/{first}").status_code == 404
        r = c.post(f"/api/sheets/{s['id']}/art?replace=true", content=png(), headers={**auth, "Content-Type": "image/png"})
        assert r.json()["art"] == [f"{s['id']}-0.png"] and not (tmp_path / "s" / "art" / f"{s['id']}-1.gif").exists()
        # down with the sheet
        c.delete(f"/api/sheets/{s['id']}", headers=auth)
        assert not list((tmp_path / "s" / "art").iterdir())


def test_what_the_crisper_refuses(tmp_path):
    with client(tmp_path) as c:
        s = c.post("/api/fridges/seren-kitchen/sheets", json={"kind": "art", "title": "x"}).json()
        assert c.post(f"/api/sheets/{s['id']}/art", content=b"hello", headers={"Content-Type": "text/plain"}).status_code == 415
        assert c.post(f"/api/sheets/{s['id']}/art", content=b"", headers={"Content-Type": "image/png"}).status_code == 400
        assert c.post(f"/api/sheets/{s['id']}/art", content=b"x" * (MAX_ART + 1), headers={"Content-Type": "image/png"}).status_code == 413
        assert c.post("/api/sheets/nope/art", content=png(), headers={"Content-Type": "image/png"}).status_code == 404
        assert c.get("/api/art/../../etc/passwd").status_code in (404, 400)
        assert c.get("/api/art/deadbeef1234.png").status_code == 404
        r = c.patch(f"/api/sheets/{s['id']}", json={"art": "anything.png"})
        assert r.status_code == 400 and "has no art" in r.text                # the pointer is set only by an upload
        assert "art" in c.get("/health").json()["features"]
