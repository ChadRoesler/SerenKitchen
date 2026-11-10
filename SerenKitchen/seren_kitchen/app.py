"""The FastAPI app: the kitchen's page and the API behind it.

Everything here is a few verbs on three nouns (store.py): fridges have facts on
the freezer, magnets stick to fridges, sheets get left, ticked, picked and taken
down. The browser holds the kitchen's bearer (the Meninges token modal); fonts are
public because a stylesheet cannot send one.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from seren_meninges.auth import DEFAULT_PUBLIC_PATHS, bearer_auth_middleware
from seren_sinew.request_log import RequestLoggingMiddleware

from . import __version__ as APP_VERSION
from ._describe import ACCENT, NAME
from ._diag import diag
from .config import KitchenConfig, load_config
from .freezer import Freezer, token_from_env
from .settings import FONT_SLOTS, Settings
from .store import KINDS, PLACES, KitchenError, Store

try:
    from seren_meninges.viewer import render_from_dir
except Exception:  # noqa: BLE001 - the API stands without the shell, and the viewer says so
    render_from_dir = None  # type: ignore[assignment]

_VIEWER_DIR = Path(__file__).parent / "viewer" / "ui"
FONT_TYPES = {".ttf": "font/ttf", ".otf": "font/otf", ".woff": "font/woff", ".woff2": "font/woff2"}
ART_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
ART_NAME = re.compile(r"[0-9a-f]{12}(-\d+)?\.(png|jpg|gif|webp)")
MAX_ART = 8 * 1024 * 1024
FEATURES = ["fridges", "magnets", "sheets", "shelves", "decisions", "leftovers", "fonts", "replies", "freezer", "art", "settings", "big-fridge"]
# the house's own fridge: its sheets go on the big fridge's door and freezer, not on a polaroid
HOUSE_FRIDGE = "seren-project"


def _store(request: Request) -> Store:
    return request.app.state.store


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _refuse(exc: ValueError) -> HTTPException:
    return HTTPException(400, str(exc))


def _body(request_json: Any) -> dict[str, Any]:
    if not isinstance(request_json, dict):
        raise HTTPException(400, "expected a JSON object")
    return request_json


def create_app(config: Optional[KitchenConfig] = None, *, github_transport: Optional[httpx.AsyncBaseTransport] = None,
               run_freezer: bool = True) -> FastAPI:
    cfg = config or load_config()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # the yaml is what an installer knows; settings.json in the state folder is what the house decided after
        app.state.settings = Settings(cfg.state_path)
        st = app.state.settings
        fridges = st.effective_fridges(cfg.fridges)
        sour = st.data.get("sour_after_days")
        app.state.store = Store(cfg.state_path / "kitchen.json", fridges,
                                sour_after_days=float(sour) if sour is not None else cfg.sour_after_days)
        gh = st.data.get("github") or {}
        app.state.freezer = Freezer(app.state.store, fridges, interval_minutes=float(gh.get("interval_minutes") or cfg.github.interval_minutes),
                                    token=token_from_env(cfg.github.token_env), transport=github_transport,
                                    token_source=st.token)
        enabled = gh.get("enabled") if gh.get("enabled") is not None else cfg.github.enabled
        task = asyncio.create_task(app.state.freezer.run()) if (run_freezer and enabled) else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()

    app = FastAPI(title="SerenKitchen", version=APP_VERSION, lifespan=lifespan)
    app.state.cfg = cfg

    # Open on loopback with no token, like the rest of the family; enforce_server refuses a wider
    # bind without one before this ever runs. /api/fonts is public: a stylesheet cannot send a bearer.
    app.add_middleware(bearer_auth_middleware(cfg.server.resolve_bearer(), public_paths=DEFAULT_PUBLIC_PATHS | {"/api/fonts", "/api/art"}))
    app.add_middleware(RequestLoggingMiddleware, service_name=NAME, env_prefix="SEREN_KITCHEN")

    try:
        from seren_meninges.updates import UpdateChecker
        app.state.updates = UpdateChecker(NAME, enabled=cfg.updates.enabled, index_url=cfg.updates.index_url,
                                          ttl_seconds=cfg.updates.check_interval_hours * 3600.0,
                                          allow_prerelease=cfg.updates.allow_prerelease, fallback_version=APP_VERSION)
    except Exception as exc:  # noqa: BLE001 - cosmetic, never fatal
        app.state.updates = None
        diag(f"[seren-kitchen] update checking unavailable ({exc})")

    @app.exception_handler(KitchenError)
    async def _refused(_request: Request, exc: KitchenError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/")
    async def root(request: Request) -> dict:
        """The family's info route: who this is, where the page is, and the updates block with its
        seven keys whatever state the checker is in (CI pins them)."""
        try:
            from seren_meninges.updates import updates_payload
            updates = await updates_payload(getattr(request.app.state, "updates", None),
                                            distribution=NAME, installed=APP_VERSION)
        except Exception as exc:  # noqa: BLE001 - an info route never 500s over a cosmetic check
            updates = {"status": "unavailable", "distribution": NAME, "installed": APP_VERSION, "latest": None,
                       "update_available": False, "checked_at": None,
                       "detail": f"update checking could not be constructed ({exc}): pip install -U seren-kitchen"}
        return {"service": NAME, "version": APP_VERSION, "viewer": "/viewer", "updates": updates}

    @app.get("/health")
    async def health():
        return {"ok": True, "service": NAME, "version": APP_VERSION, "features": FEATURES}

    # ── the wall ──────────────────────────────────────────────────────────────
    @app.get("/api/kitchen")
    async def kitchen(request: Request) -> JSONResponse:
        """The whole wall in one call: every fridge with its facts and counts, every magnet, and the
        sheets on the doors (the glance). Inside a fridge is a second call."""
        st = _store(request); se = _settings(request)
        hands = set(se.hands()) | {a for a in cfg.fonts.hands if cfg.fonts.hand_for(a) and cfg.fonts.hand_for(a).is_file()}
        sh = se.data.get("house") or {}
        house = {"person": sh.get("person") or cfg.house.person, "partner": sh.get("partner") or cfg.house.partner,
                 "notes_at": sh.get("notes_at") or "top", "hinge": sh.get("hinge") or "right", "fridge": HOUSE_FRIDGE}
        return JSONResponse({"fridges": st.fridges(), "magnets": st.magnets(),
                             "doors": st.sheets(place="door"), "kinds": list(KINDS), "places": list(PLACES),
                             "fonts": {slot: bool(se.font_file(slot) or cfg.fonts.path(slot)) for slot in FONT_SLOTS},
                             "hands": sorted(hands), "house": house,
                             "sour_after_days": st.sour_after / 86400.0},
                            headers={"Cache-Control": "no-store"})

    # ── settings: what the house decides after moving in, from the page ───────
    def _rewall(request: Request) -> list[dict[str, Any]]:
        fridges = _settings(request).effective_fridges(cfg.fridges)
        _store(request).set_fridges(fridges)
        request.app.state.freezer.set_fridges(fridges)
        return fridges

    @app.get("/api/settings")
    async def settings_view(request: Request):
        """Everything the page can change, and what the yaml gave as the floor. Never the token."""
        se = _settings(request)
        return {**se.view(), "yaml": {"fonts": {s: bool(cfg.fonts.path(s)) for s in FONT_SLOTS}, "hands": sorted(cfg.fonts.hands),
                                      "github": {"interval_minutes": cfg.github.interval_minutes, "enabled": cfg.github.enabled,
                                                 "token_env": cfg.github.token_env, "token_env_set": bool(token_from_env(cfg.github.token_env))},
                                      "house": {"person": cfg.house.person, "partner": cfg.house.partner}, "sour_after_days": cfg.sour_after_days,
                                      "fridges": [f["name"] for f in cfg.fridges]}}

    @app.post("/api/settings/fonts/{slot}")
    async def put_font(request: Request, slot: str):
        """The request body IS the font file (TTF, OTF, WOFF, WOFF2; 6 MB at most), for a slot: name, freezer, hand."""
        try:
            name = _settings(request).put_font(slot, await request.body(), request.headers.get("content-type") or "")
        except ValueError as exc:
            raise _refuse(exc)
        return {"slot": slot, "file": name}

    @app.delete("/api/settings/fonts/{slot}")
    async def drop_font(request: Request, slot: str):
        if not _settings(request).drop_font(slot=slot):
            raise HTTPException(404, f"no uploaded font for {slot!r}")
        return {"ok": True}

    @app.post("/api/settings/fonts/hand/{author}")
    async def put_hand(request: Request, author: str):
        """One author's own hand, as the request body. A sheet signed by that name is drawn in it."""
        try:
            name = _settings(request).put_font("hand", await request.body(), request.headers.get("content-type") or "", author=author)
        except ValueError as exc:
            raise _refuse(exc)
        return {"author": author.strip().lower(), "file": name}

    @app.delete("/api/settings/fonts/hand/{author}")
    async def drop_hand(request: Request, author: str):
        if not _settings(request).drop_font(author=author):
            raise HTTPException(404, f"no hand for {author!r}")
        return {"ok": True}

    @app.post("/api/settings/github")
    async def set_github(request: Request):
        """{"token": "...", "interval_minutes": 15, "enabled": true}: any of them. The token is written to a file in
        the state folder, 600, and never read back out; an empty token forgets it. The freezer asks the file first,
        the yaml's env var second."""
        body = _body(await request.json()); se = _settings(request)
        try:
            if "token" in body:
                se.set_token(str(body.get("token") or ""))
            out = se.set_github(interval_minutes=body.get("interval_minutes"), enabled=body.get("enabled"))
        except ValueError as exc:
            raise _refuse(exc)
        if body.get("interval_minutes") is not None:
            request.app.state.freezer.interval = max(1.0, float(body["interval_minutes"])) * 60.0
        return {**out, "token_set": se.token_set()}

    @app.post("/api/settings/house")
    async def set_house(request: Request):
        """{"person", "partner", "notes_at": "top|bottom", "hinge": "left|right"}, any of them."""
        body = _body(await request.json())
        try:
            return _settings(request).set_house(person=body.get("person"), partner=body.get("partner"), notes_at=body.get("notes_at"), hinge=body.get("hinge"))
        except ValueError as exc:
            raise _refuse(exc)

    @app.post("/api/settings/sour")
    async def set_sour(request: Request):
        body = _body(await request.json())
        try:
            days = _settings(request).set_sour(float(body.get("days")))
        except (TypeError, ValueError):
            raise HTTPException(400, "days is a number")
        _store(request).sour_after = days * 86400.0
        return {"sour_after_days": days}

    @app.post("/api/settings/fridges")
    async def add_fridge(request: Request):
        """{"name": "my-thing", "display": "My Thing", "group": "other", "accent": "#7fd1c1", "repo": "me/my-thing"}"""
        body = _body(await request.json())
        try:
            f = _settings(request).add_fridge(str(body.get("name") or ""), display=str(body.get("display") or ""), group=str(body.get("group") or "other"),
                                              accent=str(body.get("accent") or "#cccccc"), repo=str(body.get("repo") or ""))
        except ValueError as exc:
            raise _refuse(exc)
        _rewall(request)
        return f

    @app.patch("/api/settings/fridges/{name}")
    async def change_fridge(request: Request, name: str):
        """Any of display, group, accent, repo, hidden (true takes it off the wall; its sheets wait)."""
        body = _body(await request.json())
        known = {f["name"] for f in cfg.fridges} | {x.get("name") for x in _settings(request).data["fridges"]["extra"]}
        if name not in known:
            raise HTTPException(404, f"no fridge called {name!r}")
        try:
            ov = _settings(request).change_fridge(name, **{k: body.get(k) for k in ("display", "group", "accent", "repo", "hidden") if k in body})
        except ValueError as exc:
            raise _refuse(exc)
        _rewall(request)
        return {"name": name, "overrides": ov, "hidden": name in _settings(request).data["fridges"]["hidden"]}

    @app.post("/api/settings/order")
    async def set_order(request: Request):
        """{"order": ["seren-kitchen", "seren-memory", ...]}: the wall's order, left to right, top to bottom."""
        body = _body(await request.json())
        order = body.get("order")
        if not isinstance(order, list):
            raise HTTPException(400, "order is a list of fridge names")
        _settings(request).set_order([str(n) for n in order])
        return {"order": [f["name"] for f in _rewall(request)]}

    @app.get("/api/fridges/{name}")
    async def fridge(request: Request, name: str) -> JSONResponse:
        """One fridge, opened: the door, each shelf, the crisper and the leftovers, and who is holding it."""
        st = _store(request)
        f = next((f for f in st.fridges() if f["name"] == name), None)
        if f is None:
            raise HTTPException(404, f"no fridge called {name!r}")
        return JSONResponse({**f, "magnets": [m for m in st.magnets() if m.get("fridge") == name],
                             "door": st.sheets(fridge=name, place="door"), "shelf": st.sheets(fridge=name, place="shelf"),
                             "crisper": st.sheets(fridge=name, place="crisper"),
                             "leftovers": st.sheets(fridge=name, place="leftovers")},
                            headers={"Cache-Control": "no-store"})

    @app.post("/api/fridges/{name}/facts")
    async def facts(request: Request, name: str):
        """What the freezer shows: {"release": "5.6.1", "build": "ok", ...}, any keys, strings; null forgets one.
        The freezer fills release and build from GitHub on its own; this is for anything else, or a hand."""
        body = _body(await request.json())
        return _store(request).set_facts(name, **{str(k): v for k, v in body.items()})

    @app.post("/api/fridges/{name}/freezer")
    async def fridge_freezer(request: Request, name: str):
        """The dispenser button: read GitHub for this one fridge now."""
        if name not in _store(request).fridge_names():
            raise HTTPException(404, f"no fridge called {name!r}")
        res = await request.app.state.freezer.refresh_one(name)
        if "error" in res:
            raise HTTPException(502, res["error"])
        return res

    @app.post("/api/freezer/refresh")
    async def freezer_refresh(request: Request):
        """Read GitHub for every fridge now, without waiting for the next pass."""
        res = await request.app.state.freezer.run_once()
        return {"read": sum(1 for f in res.values() if "error" not in f), "unreadable": {n: f["error"] for n, f in res.items() if "error" in f},
                "passes": request.app.state.freezer.passes, "last_pass": request.app.state.freezer.last_pass}

    # ── magnets ───────────────────────────────────────────────────────────────
    @app.get("/api/magnets")
    async def magnets(request: Request):
        return _store(request).magnets()

    @app.post("/api/magnets")
    async def make_magnet(request: Request):
        """{"partner": "ada", "starter": "the text that starts my session", "picture": "data:image/png;base64,..."}:
        make or update a magnet. The picture is each partner's own; the kitchen ships with none."""
        body = _body(await request.json())
        return _store(request).set_magnet(str(body.get("partner") or ""), starter=body.get("starter"), picture=body.get("picture"))

    @app.post("/api/magnets/{partner}/stick")
    async def stick(request: Request, partner: str):
        """{"fridge": "seren-memory", "x": 14, "y": 12}: this partner holds that repo now. {"fridge": null}: off
        the wall, onto the counter."""
        body = _body(await request.json())
        return _store(request).stick(partner, body.get("fridge"), body.get("x"), body.get("y"))

    @app.delete("/api/magnets/{partner}")
    async def drop_magnet(request: Request, partner: str):
        if not _store(request).drop_magnet(partner):
            raise HTTPException(404, f"no magnet for {partner!r}")
        return {"ok": True}

    # ── sheets ────────────────────────────────────────────────────────────────
    @app.get("/api/sheets")
    async def sheets(request: Request, fridge: Optional[str] = None, kind: Optional[str] = None,
                     place: Optional[str] = None, author: Optional[str] = None, open: bool = False, replies: bool = False,
                     waiting: bool = False):
        return _store(request).sheets(fridge=fridge, kind=kind, place=place, author=author, open_only=open, replies=replies,
                                      waiting=waiting)

    @app.get("/api/sheets/{sheet_id}")
    async def sheet(request: Request, sheet_id: str):
        s = _store(request).sheet(sheet_id)
        if s is None:
            raise HTTPException(404, f"no sheet {sheet_id!r}")
        return s

    @app.post("/api/fridges/{name}/sheets")
    async def leave(request: Request, name: str):
        """Leave a sheet on a fridge: {"kind": "now|list|person|self|other|art|decision", "title": "...",
        "lines": ["..."], "author": "...", "pin": "#d0393e", "options": [...] (a decision)}. Its kind
        says where it sits; `place` overrides."""
        body = _body(await request.json())
        return _store(request).leave(fridge=name, kind=str(body.get("kind") or "now"), title=str(body.get("title") or ""),
                                     lines=body.get("lines"), author=str(body.get("author") or ""), pin=str(body.get("pin") or ""),
                                     options=body.get("options"), place=body.get("place"), x=body.get("x"), y=body.get("y"),
                                     rot=body.get("rot"), body=str(body.get("body") or ""), reply_to=body.get("reply_to"),
                                     reply_line=body.get("reply_line"), ref=str(body.get("ref") or ""), made=body.get("made"),
                                     done=bool(body.get("done")))

    @app.post("/api/sheets/{sheet_id}/reply")
    async def reply(request: Request, sheet_id: str):
        """Stick a sheet to a sheet: the same body as leaving one, without a fridge (it lives where its
        parent lives); `line` names the line it answers."""
        body = _body(await request.json())
        parent = _store(request).sheet(sheet_id)
        if parent is None:
            raise HTTPException(404, f"no sheet {sheet_id!r}")
        return _store(request).leave(fridge=parent["fridge"], kind=str(body.get("kind") or "other"), title=str(body.get("title") or ""),
                                     lines=body.get("lines"), author=str(body.get("author") or ""), pin=str(body.get("pin") or ""),
                                     body=str(body.get("body") or ""), reply_to=sheet_id, reply_line=body.get("line"))

    @app.patch("/api/sheets/{sheet_id}")
    async def change(request: Request, sheet_id: str):
        """Any of: title, lines (replace), add_lines, tick [i], untick [i], place, x, y, rot, pin, fridge,
        done (true: to the leftovers), pick (a decision's option, which also finishes it)."""
        body = _body(await request.json())
        allowed = {"title", "lines", "add_lines", "tick", "untick", "place", "x", "y", "rot", "pin", "fridge", "done", "pick", "body",
                   "pick_line"}
        # `art` is set by POST /api/sheets/{id}/art, which writes the file; a bare pointer would dangle
        unknown = set(body) - allowed
        if unknown:
            raise HTTPException(400, f"a sheet has no {', '.join(sorted(unknown))}; it takes {', '.join(sorted(allowed))}")
        return _store(request).change(sheet_id, **body)

    @app.delete("/api/sheets/{sheet_id}")
    async def take_down(request: Request, sheet_id: str):
        st = _store(request)
        s = st.sheet(sheet_id)
        if s is None:
            raise HTTPException(404, f"no sheet {sheet_id!r}")
        doomed = [s] + list(s.get("replies") or [])
        st.take_down(sheet_id)
        for d in doomed:                                   # the pictures come down with their sheet
            for name in d.get("art") or []:
                try:
                    (cfg.state_path / "art" / name).unlink()
                except OSError:
                    pass
        return {"ok": True}

    # ── art: pictures on a sheet, kept as files beside the store ───────────────
    @app.post("/api/sheets/{sheet_id}/art")
    async def put_art(request: Request, sheet_id: str, replace: bool = False):
        """The request body IS the picture (Content-Type image/png, image/jpeg, image/gif or image/webp,
        8 MB at most). It is kept as <state>/art/<sheet id>-<n>.<ext> and joins the sheet's pictures;
        ?replace=true clears the others first. Macaroni welcome, in any quantity."""
        st = _store(request)
        s = st.sheet(sheet_id)
        if s is None:
            raise HTTPException(404, f"no sheet {sheet_id!r}")
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        ext = ART_TYPES.get(ctype)
        if not ext:
            raise HTTPException(415, f"a picture is one of {', '.join(ART_TYPES)}; not {ctype or 'nothing'}")
        data = await request.body()
        if not data:
            raise HTTPException(400, "the picture was empty")
        if len(data) > MAX_ART:
            raise HTTPException(413, f"that picture is {len(data) // 1024} KB; the fridge takes up to {MAX_ART // (1024 * 1024)} MB")
        folder = cfg.state_path / "art"
        folder.mkdir(parents=True, exist_ok=True)
        have = list(s.get("art") or [])
        if replace:
            for old in have:
                try:
                    (folder / old).unlink()
                except OSError:
                    pass
            have = []
        n = 0
        while (folder / f"{sheet_id}-{n}.{ext}").exists() or any(a.startswith(f"{sheet_id}-{n}.") for a in have):
            n += 1
        name = f"{sheet_id}-{n}.{ext}"
        (folder / name).write_bytes(data)
        return st.change(sheet_id, art=have + [name])

    @app.delete("/api/sheets/{sheet_id}/art/{name}")
    async def drop_art(request: Request, sheet_id: str, name: str):
        """One picture off a sheet."""
        st = _store(request)
        s = st.sheet(sheet_id)
        if s is None or name not in (s.get("art") or []):
            raise HTTPException(404, "no such picture on that sheet")
        try:
            (cfg.state_path / "art" / name).unlink()
        except OSError:
            pass
        return st.change(sheet_id, art=[a for a in s["art"] if a != name])

    @app.get("/api/art/{name}", include_in_schema=False)
    async def get_art(name: str):
        """A sheet's picture. Public, like the fonts: an <img> cannot send a bearer."""
        if not ART_NAME.fullmatch(name):
            raise HTTPException(404, "no such picture")
        p = cfg.state_path / "art" / name
        if not p.is_file():
            raise HTTPException(404, "no such picture")
        ctype = next((c for c, e in ART_TYPES.items() if name.endswith("." + e)), "application/octet-stream")
        return FileResponse(str(p), media_type=ctype, headers={"Cache-Control": "public, max-age=3600"})

    # ── fonts ─────────────────────────────────────────────────────────────────
    @app.get("/api/fonts/hand/{author}", include_in_schema=False)
    async def hand_of(request: Request, author: str):
        """One author's own hand: uploaded from the page first, the yaml's fonts.hands second. 404 when they have
        none: the page uses the house hand."""
        p = _settings(request).hand_file(author) or cfg.fonts.hand_for(author)
        if p is None or not p.is_file():
            raise HTTPException(404, f"no hand for {author!r}")
        return FileResponse(str(p), media_type=FONT_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                            headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/api/fonts/{slot}", include_in_schema=False)
    async def font(request: Request, slot: str):
        """The font for a slot (name, freezer, hand): uploaded from the page first, the yaml's path second. 404
        when neither: the page's @font-face falls through to its system fallbacks."""
        if slot not in FONT_SLOTS:
            raise HTTPException(404, "slots are name, freezer and hand")
        p = _settings(request).font_file(slot) or cfg.fonts.path(slot)
        if p is None or not p.is_file():
            raise HTTPException(404, f"no {slot} font configured")
        return FileResponse(str(p), media_type=FONT_TYPES.get(p.suffix.lower(), "application/octet-stream"),
                            headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/viewer", include_in_schema=False)
    async def viewer():
        if render_from_dir is None:
            return HTMLResponse("<h1>SerenKitchen</h1><p>The SerenMeninges UI shell is not importable, "
                                "so the kitchen can't render. <code>pip install seren-meninges</code></p>",
                                status_code=503)
        return HTMLResponse(headers={"Cache-Control": "no-store, must-revalidate"}, content=render_from_dir(
            _VIEWER_DIR, title="SerenKitchen", brand="Seren<b>Kitchen</b>",
            subtitle=f"v{APP_VERSION} · a fridge per app, and the notes we leave each other", accent=ACCENT))

    return app
