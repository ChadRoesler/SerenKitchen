"""The FastAPI app: the kitchen's page and the API behind it.

Everything here is a few verbs on three nouns (store.py): fridges have facts on
the freezer, magnets stick to fridges, sheets get left, ticked, picked and taken
down. The browser holds the kitchen's bearer (the Meninges token modal); fonts are
public because a stylesheet cannot send one.
"""
from __future__ import annotations

import asyncio
import re
from contextlib import AsyncExitStack, asynccontextmanager
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
from .config import KitchenConfig, house_fridge, load_config
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
FEATURES = ["fridges", "magnets", "sheets", "shelves", "decisions", "leftovers", "fonts", "replies", "freezer", "art", "settings", "big-fridge",
            "faces", "gallery", "magnet-drawer", "stores"]
FACE_TYPES = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}


def _store(request: Request) -> Store:
    return request.app.state.store


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _life(st: Store) -> dict[str, Any]:
    """A magnet's life as the house has it set."""
    return {"grey_after_hours": st.grey_after / 3600.0, "drawer_after_days": st.drawer_after / 86400.0, "stick_on_start": st.stick_on_start}


def _wall(se: Settings, cfg: KitchenConfig) -> list[dict[str, Any]]:
    """Every fridge on the wall: the yaml's, then the page's, and always the house's own. Its sheets go on the big
    fridge's door and freezer, not on a polaroid, so it is put back if the yaml left it out or the page hid it."""
    fridges = se.effective_fridges(cfg.fridges)
    if not any(f["name"] == cfg.house.fridge for f in fridges):
        fridges.append(house_fridge(cfg.house.fridge))
    return fridges


def _house(se: Settings, cfg: KitchenConfig) -> dict[str, str]:
    """What the house calls its person and its partner: the page's say first, the yaml's second, blank when neither."""
    sh = se.data.get("house") or {}
    return {"person": sh.get("person") or cfg.house.person, "partner": sh.get("partner") or cfg.house.partner}


def _signs_as(se: Settings, cfg: KitchenConfig) -> str:
    """The one name the MCP tools sign with: the yaml's mcp.author, else the house's partner."""
    return cfg.mcp.author or _house(se, cfg)["partner"] or "the partner"


def _refuse(exc: ValueError) -> HTTPException:
    return HTTPException(400, str(exc))


def _body(request_json: Any) -> dict[str, Any]:
    if not isinstance(request_json, dict):
        raise HTTPException(400, "expected a JSON object")
    return request_json


def _declared(cfg: KitchenConfig) -> list:
    """What the kitchen keeps on disk, for a snapshot and for a restore (seren_sinew.stores). kitchen.json is
    the kitchen; the rest is optional on a restore, since a snapshot from before it existed holds none of it.
    The GitHub token is a file in the same folder and is deliberately not here: a backup is not a way out
    for a secret that is never read back."""
    from seren_sinew.stores import Store as Kept
    st = cfg.state_path
    return [Kept("kitchen", "file", str(st / "kitchen.json"), "the sheets, the magnets, the freezer's facts and the faces' gallery"),
            Kept("settings", "file", str(st / "settings.json"), "what the house decided from the page: fridges, names, milk", optional=True),
            Kept("art", "dir", str(st / "art"), "the pictures on the sheets", optional=True),
            Kept("faces", "dir", str(st / "faces"), "the pictures the magnets wear, and have worn", optional=True),
            Kept("fonts", "dir", str(st / "fonts"), "fonts and hands uploaded from the page", optional=True)]


def _check(restored: dict, manifest: dict, snapshot: Path) -> dict:
    """A rehearsal's look at a restored COPY: kitchen.json read and counted, and every picture it names
    looked for in the copied folders."""
    import json as _json
    k = _json.loads((restored["kitchen"] / "kitchen.json").read_text(encoding="utf-8"))
    sheets, magnets, faces = k.get("sheets") or {}, k.get("magnets") or {}, k.get("faces") or {}
    art = [a for s in sheets.values() for a in (s.get("art") or [])]
    worn = {f.get("file") for f in faces.values()} | {(m.get("picture") or "")[len("/api/faces/"):] for m in magnets.values()
                                                      if (m.get("picture") or "").startswith("/api/faces/")}
    lost_art = [a for a in art if "art" not in restored or not (restored["art"] / a).is_file()]
    lost_faces = [f for f in worn if f and ("faces" not in restored or not (restored["faces"] / f).is_file())]
    rep: dict = {"counts": {"sheets": len(sheets), "magnets": len(magnets), "faces": len(faces)}}
    problems = []
    if lost_art:
        problems.append(f"{len(lost_art)} of the {len(art)} picture(s) the sheets name are not in the copy")
    if lost_faces:
        problems.append(f"{len(lost_faces)} of the {len(worn)} face(s) the magnets and the gallery name are not in the copy")
    if problems:
        rep["problems"] = problems
    return rep


def create_app(config: Optional[KitchenConfig] = None, *, github_transport: Optional[httpx.AsyncBaseTransport] = None,
               run_freezer: bool = True) -> FastAPI:
    cfg = config or load_config()
    from seren_sinew.stores import StoreKeeper, add_store_routes, restore_at_startup, snapshot_loop

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # A restore, when the yaml asks for one (backup.restore_from + restore_reason): into an empty kitchen only,
        # before the store opens. Refused = the kitchen does not start. No route does this.
        if cfg.backup.restore_from.strip():
            restore_at_startup(NAME, _declared(cfg), cfg.backup.restore_from, cfg.backup.restore_reason,
                               cfg.backup_path / NAME, log=lambda m: diag(f"[seren-kitchen] {m}"))
        # the yaml is what an installer knows; settings.json in the state folder is what the house decided after
        app.state.settings = Settings(cfg.state_path)
        st = app.state.settings
        fridges = _wall(st, cfg)
        sour = st.data.get("sour_after_days")
        # a magnet's life: the page's say first, the yaml's (an installer's defaults) second
        life = st.data.get("magnets") or {}
        app.state.store = Store(cfg.state_path / "kitchen.json", fridges,
                                sour_after_days=float(sour) if sour is not None else cfg.sour_after_days,
                                grey_after_hours=float(life.get("grey_after_hours") or cfg.magnets.grey_after_hours),
                                drawer_after_days=float(life.get("drawer_after_days") or cfg.magnets.drawer_after_days),
                                house_fridge=cfg.house.fridge, trim_prefix=cfg.magnets.trim_prefix)
        # sheets kept for fridges the wall no longer has (a yaml that lost its fridge list, say) are never thrown
        # out; say so at the door, so an emptier wall than yesterday's reads as a config to fix, not a loss
        waiting = app.state.store.off_the_wall()
        if waiting:
            diag(f"[seren-kitchen] {sum(waiting.values())} sheet(s) kept for fridges not on the wall, back when they are: "
                 + ", ".join(f"{n or '(none)'} {c}" for n, c in sorted(waiting.items())))
        sos = life.get("stick_on_start")
        app.state.store.stick_on_start = bool(sos) if sos is not None else cfg.magnets.stick_on_start
        gh = st.data.get("github") or {}
        app.state.freezer = Freezer(app.state.store, fridges, interval_minutes=float(gh.get("interval_minutes") or cfg.github.interval_minutes),
                                    token=token_from_env(cfg.github.token_env), transport=github_transport,
                                    token_source=st.token)
        enabled = gh.get("enabled") if gh.get("enabled") is not None else cfg.github.enabled
        task = asyncio.create_task(app.state.freezer.run()) if (run_freezer and enabled) else None
        # snapshots on the kitchen's own schedule, so a kitchen with no Lodestar is still backed up
        snaps = asyncio.create_task(snapshot_loop(lambda: app.state.stores, cfg.backup.every_hours)) \
            if (app.state.stores is not None and cfg.backup.every_hours > 0) else None
        # The kitchen's own door for a partner in a house with no Workbench: /mcp, the tools on this store. Only
        # with the [mcp] extra installed; without it, or if the mount fails, the kitchen is the page and the API.
        mcp_server = None
        app.state.mcp_path = None
        if cfg.mcp.enabled:
            try:
                from .mcp.server import mount_mcp_routes
                from .mcp.tools import KitchenToolImpl
                mcp_server = mount_mcp_routes(app, KitchenToolImpl(app.state.store, author=lambda: _signs_as(st, cfg),
                                                                   house=lambda: _house(st, cfg)))
                diag(f"[seren-kitchen] MCP at {app.state.mcp_path}, signing as {_signs_as(st, cfg)!r}")
            except ImportError as exc:
                diag(f"[seren-kitchen] no MCP endpoint ({exc}): pip install 'seren-kitchen[mcp]' for one")
            except Exception as exc:  # noqa: BLE001 - a door that will not hang never takes the kitchen down
                app.state.mcp_path = None
                diag(f"[seren-kitchen] MCP mount failed: {exc!r}; continuing without it")
        try:
            # the streamable-HTTP transport's task group lives in the session manager, and a mounted sub-app's own
            # lifespan never fires, so it is run here; with nothing mounted the stack is empty
            async with AsyncExitStack() as stack:
                manager = getattr(mcp_server, "session_manager", None)
                if manager is not None:
                    await stack.enter_async_context(manager.run())
                yield
        finally:
            for t in (task, snaps):
                if t is not None:
                    t.cancel()

    app = FastAPI(title="SerenKitchen", version=APP_VERSION, lifespan=lifespan)
    app.state.cfg = cfg
    app.state.mcp_path = None

    # Open on loopback with no token, like the rest of the family; enforce_server refuses a wider
    # bind without one before this ever runs. /api/fonts is public: a stylesheet cannot send a bearer.
    app.add_middleware(bearer_auth_middleware(cfg.server.resolve_bearer(), public_paths=DEFAULT_PUBLIC_PATHS | {"/api/fonts", "/api/art", "/api/faces"}))
    app.add_middleware(RequestLoggingMiddleware, service_name=NAME, env_prefix="SEREN_KITCHEN")

    # ── what the kitchen keeps, and snapshots of it (seren_sinew.stores): GET /stores, POST /stores/snapshot,
    # GET /stores/snapshots, the archive a Lodestar pulls, and the rehearsal. No route restores or deletes one.
    def _extra() -> dict:
        st = getattr(app.state, "store", None)
        return {"version": APP_VERSION, "counts": {"sheets": len(st), "magnets": len(st.magnets()), "faces": len(st.faces())} if st else {}}

    app.state.stores = StoreKeeper(NAME, lambda: _declared(cfg), cfg.backup_path, extra=_extra, check=_check,
                                   keep_daily=cfg.backup.keep_daily, keep_weekly=cfg.backup.keep_weekly, compress=cfg.backup.compress,
                                   log=lambda m: diag(f"[seren-kitchen] {m}")) if cfg.backup.enabled else None
    add_store_routes(app, lambda: app.state.stores, archive_allowed=lambda: cfg.backup.allow_pull,
                     archive_refusal="this kitchen's snapshots stay on this box (backup.allow_pull is off).")

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
        return {"service": NAME, "version": APP_VERSION, "viewer": "/viewer", "mcp": request.app.state.mcp_path, "updates": updates}

    @app.get("/health")
    async def health(request: Request):
        # `mcp` is where the kitchen's own MCP endpoint is mounted, or null when it is not (no [mcp] extra, or off)
        return {"ok": True, "service": NAME, "version": APP_VERSION, "features": FEATURES, "mcp": request.app.state.mcp_path}

    # ── the wall ──────────────────────────────────────────────────────────────
    @app.get("/api/kitchen")
    async def kitchen(request: Request) -> JSONResponse:
        """The whole wall in one call: every fridge with its facts and counts, every magnet, and the
        sheets on the doors (the glance). Inside a fridge is a second call."""
        st = _store(request); se = _settings(request)
        hands = set(se.hands()) | {a for a in cfg.fonts.hands if cfg.fonts.hand_for(a) and cfg.fonts.hand_for(a).is_file()}
        sh = se.data.get("house") or {}
        house = {**_house(se, cfg), "notes_at": sh.get("notes_at") or "top", "hinge": sh.get("hinge") or "right", "fridge": cfg.house.fridge}
        return JSONResponse({"fridges": st.fridges(), "magnets": st.magnets(),
                             "doors": st.sheets(place="door"), "kinds": list(KINDS), "places": list(PLACES),
                             "fonts": {slot: bool(se.font_file(slot) or cfg.fonts.path(slot)) for slot in FONT_SLOTS},
                             "hands": sorted(hands), "house": house,
                             "sour_after_days": st.sour_after / 86400.0,
                             "magnet_life": _life(st)},
                            headers={"Cache-Control": "no-store"})

    # ── settings: what the house decides after moving in, from the page ───────
    def _rewall(request: Request) -> list[dict[str, Any]]:
        fridges = _wall(_settings(request), cfg)
        _store(request).set_fridges(fridges)
        request.app.state.freezer.set_fridges(fridges)
        return fridges

    @app.get("/api/settings")
    async def settings_view(request: Request):
        """Everything the page can change, and what the yaml gave as the floor. Never the token."""
        se = _settings(request)
        return {**se.view(), "mcp": {"path": request.app.state.mcp_path, "signs_as": _signs_as(se, cfg)},
                "off_the_wall": _store(request).off_the_wall(), "yaml": {"fonts": {s: bool(cfg.fonts.path(s)) for s in FONT_SLOTS}, "hands": sorted(cfg.fonts.hands),
                                      "github": {"interval_minutes": cfg.github.interval_minutes, "enabled": cfg.github.enabled,
                                                 "token_env": cfg.github.token_env, "token_env_set": bool(token_from_env(cfg.github.token_env))},
                                      "house": {"person": cfg.house.person, "partner": cfg.house.partner, "fridge": cfg.house.fridge}, "sour_after_days": cfg.sour_after_days,
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

    @app.post("/api/settings/magnets")
    async def set_magnet_life(request: Request):
        """{"grey_after_hours": 12, "drawer_after_days": 3, "stick_on_start": true}, any of them: how long a magnet
        stays bright, how long until a quiet one goes in the drawer, and whether a session in a fridge's repo holds it
        from its first minute."""
        body = _body(await request.json())
        try:
            out = _settings(request).set_magnets(grey_after_hours=body.get("grey_after_hours"), drawer_after_days=body.get("drawer_after_days"),
                                                 stick_on_start=body.get("stick_on_start"))
        except (TypeError, ValueError):
            raise HTTPException(400, "hours and days are numbers")
        st = _store(request)
        st.grey_after = float(out.get("grey_after_hours") or cfg.magnets.grey_after_hours) * 3600.0
        st.drawer_after = float(out.get("drawer_after_days") or cfg.magnets.drawer_after_days) * 86400.0
        if out.get("stick_on_start") is not None:
            st.stick_on_start = bool(out["stick_on_start"])
        return _life(st)

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

    @app.delete("/api/settings/fridges/{name}")
    async def remove_fridge(request: Request, name: str, move_to: str = ""):
        """A fridge added from the page, off the wall for good. ?move_to=<fridge> moves its sheets there first;
        without it they are kept (off the wall, counted in the settings) and come back if a fridge by that name is
        ever added again. Its magnets go back on the counter. The house's own fridge stays, and a fridge the yaml
        lists is the yaml's to take away (hiding it is the page's way)."""
        se = _settings(request); st = _store(request)
        if name == cfg.house.fridge:
            raise HTTPException(400, "the house's own fridge stays: it is the big fridge the wall is drawn on")
        if name in {f["name"] for f in cfg.fridges}:
            raise HTTPException(400, f"{name} is in the yaml, so it comes back on every start: take it out of the yaml, "
                                     f"or hide it here")
        if not se.added_here(name):
            raise HTTPException(404, f"no fridge called {name!r} was added from the page")
        move_to = (move_to or "").strip()
        moved = 0
        if move_to:
            if move_to == name or move_to not in st.fridge_names():
                raise HTTPException(400, f"move its sheets to a fridge on the wall, not {move_to!r}")
            moved = st.move_sheets(name, move_to)
        down = st.set_down_from(name)
        se.drop_fridge(name)
        _rewall(request)
        return {"removed": name, "sheets_moved": moved, **({"to": move_to} if move_to else {}),
                "sheets_kept": st.kept_for(name), "magnets_set_down": down}

    @app.post("/api/fridges/{name}/move")
    async def move_sheets(request: Request, name: str):
        """{"to": "<fridge>"}: every sheet kept for this fridge, on the wall or not, onto another one, the notes
        stuck on them with them. How sheets left behind by a fridge that is gone find a door again."""
        body = _body(await request.json())
        to = str(body.get("to") or "").strip()
        st = _store(request)
        if not st.kept_for(name):
            raise HTTPException(404, f"no sheets are kept for {name!r}")
        return {"from": name, "to": to, "moved": st.move_sheets(name, to)}

    @app.post("/api/settings/order")
    async def set_order(request: Request):
        """{"order": ["house", "my-app", ...]}: the wall's order, left to right, top to bottom."""
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
        return JSONResponse({**f, "magnets": [m for m in st.magnets() if m.get("fridge") == name and not m["in_drawer"]],
                             "door": st.sheets(fridge=name, place="door"), "shelf": st.sheets(fridge=name, place="shelf"),
                             "crisper": st.sheets(fridge=name, place="crisper"),
                             "leftovers": st.sheets(fridge=name, place="leftovers"),
                             "faces": st.faces(fridge=name)},
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
        return _store(request).set_magnet(str(body.get("partner") or ""), hand=str(body.get("hand") or ""), starter=body.get("starter"),
                                          picture=body.get("picture"))

    @app.post("/api/magnets/{partner}/stick")
    async def stick(request: Request, partner: str):
        """{"fridge": "my-app", "x": 14, "y": 12}: this partner holds that repo now. {"fridge": null}: off
        the wall, onto the counter."""
        body = _body(await request.json())
        return _store(request).stick(partner, body.get("fridge"), body.get("x"), body.get("y"), hand=str(body.get("hand") or ""))

    def _say(ev: str, m: dict[str, Any]) -> str:
        """What a hook prints into the session: who the kitchen thinks it is, and what to do about it."""
        hand = m.get("hand") or ""
        tools = f'Pass hand="{hand}" on the kitchen tools (kitchen_leave, kitchen_reply, kitchen_tick, kitchen_stick, kitchen_magnet).' if hand \
            else "You are the one magnet of your name; the kitchen tools need no hand."
        if ev == "end":
            return f"The kitchen marked {m['label']} ended" + (f" ({m['end_reason']})" if m.get("end_reason") else "") + ". The magnet stays where it was."
        if m.get("numbered_from"):
            head = f"Another live session of {m['partner']} holds {m['numbered_from']}; the kitchen knows this one as {m['label']}."
        elif m.get("previous") and m.get("source") in ("startup", "resume", "clear", ""):
            head = f"The kitchen knows this session as {m['label']}, taken over from session {m['previous']}."
        else:
            head = f"The kitchen knows this session as {m['label']}."
        where = f"Your magnet is on {m['fridge']}." if m.get("fridge") else "Your magnet is on the counter: kitchen_stick when you take a repo."
        if m.get("stuck"):
            where = f"This folder is {m['stuck']}'s repo, so your magnet went straight onto it."
            busy = [t["label"] for t in m.get("took_from") or [] if t.get("busy")]
            quiet = [t["label"] for t in m.get("took_from") or [] if not t.get("busy")]
            if busy:
                where += (f" {', '.join(busy)} held it and {'was' if len(busy) == 1 else 'were'} at work there within the hour: "
                          f"they are on the counter now and will be told. Check the kitchen before you change anything they may be in the middle of.")
            if quiet:
                where += f" {', '.join(quiet)} held it before you, quietly; they are on the counter now."
        return f"{head} {tools} {where}"

    @app.post("/api/sessions")
    async def sessions(request: Request):
        """A harness's session hook. {"event": "start", "partner": "ada", "session": "<id>", "cwd": "...", "harness":
        "claude", "box": "<host>", "source": "startup|resume|clear|compact", "hand": "<optional>"} makes or takes over the
        hand's magnet (the hand is read off the folder when none is given) and never sticks it; {"event": "end", ...,
        "reason": "..."} marks the magnet carrying that session ended. Both answer with the label to sign as."""
        body = _body(await request.json())
        ev = str(body.get("event") or "").strip().lower()
        st = _store(request)
        if ev == "start":
            m = st.session_start(partner=str(body.get("partner") or ""), session=str(body.get("session") or ""), cwd=str(body.get("cwd") or ""),
                                 harness=str(body.get("harness") or "claude"), box=str(body.get("box") or ""), source=str(body.get("source") or ""),
                                 hand=str(body.get("hand") or ""))
        elif ev == "end":
            m = st.session_end(partner=str(body.get("partner") or ""), session=str(body.get("session") or ""), reason=str(body.get("reason") or ""),
                               hand=str(body.get("hand") or ""))
            if m is None:
                raise HTTPException(404, "no magnet carries that session")
        elif ev == "touch":
            # a prompt was sent in the session: it is still at work. `say` is empty unless it has something to learn
            # (its fridge or its hand was taken over while it was quiet); a hook prints it into the session.
            m, note = st.touch(partner=str(body.get("partner") or ""), session=str(body.get("session") or ""), hand=str(body.get("hand") or ""))
            if m is None:
                raise HTTPException(404, "no magnet carries that session")
            return {"ok": True, "label": m["label"], "hand": m["hand"], "on": m.get("fridge"), "state": m["state"], "say": note}
        else:
            raise HTTPException(400, "event is start, touch or end")
        return {"ok": True, "label": m["label"], "hand": m["hand"], "on": m.get("fridge"), "state": m["state"], "starter": m.get("starter", ""),
                "say": _say(ev, m)}

    @app.post("/api/magnets/{partner}/drawer")
    async def drawer(request: Request, partner: str):
        """{"hand": "...", "away": true}: into the drawer under the counter (off its fridge, if it was on one);
        {"away": false}: back out onto the counter. A loose magnet whose session ended goes in on its own."""
        body = _body(await request.json())
        return _store(request).put_away(partner, bool(body.get("away", True)), hand=str(body.get("hand") or ""))

    @app.delete("/api/magnets/{partner}")
    async def drop_magnet(request: Request, partner: str, hand: str = ""):
        """Off the board for good. The faces it wore stay in the gallery."""
        if not _store(request).drop_magnet(partner, hand):
            raise HTTPException(404, f"no magnet for {partner!r}")
        return {"ok": True}

    # ── faces: the pictures magnets wear, and the gallery of every one they have worn ──
    @app.get("/api/gallery")
    async def gallery(request: Request, fridge: Optional[str] = None):
        """Every face a magnet has worn, newest first, each with the fridge it was hung on and who wears it now.
        ?fridge=my-app for one fridge's; ?fridge= (blank) for the ones that belong to none."""
        return _store(request).faces(fridge=fridge)

    @app.delete("/api/gallery/{face_id}")
    async def drop_face(request: Request, face_id: str):
        """One face out of the gallery. A magnet still wearing it keeps it."""
        if not _store(request).drop_face(face_id):
            raise HTTPException(404, f"no face {face_id!r} in the gallery")
        return {"ok": True}

    @app.get("/api/faces/{name}", include_in_schema=False)
    async def face(request: Request, name: str):
        """A magnet's face. Public, like the art: an <img> cannot send a bearer. Named by what is in it, so it
        never changes under its name."""
        p = _store(request).face_file(name)
        if p is None:
            raise HTTPException(404, "no such face")
        return FileResponse(str(p), media_type=FACE_TYPES.get(p.suffix.lstrip(".").lower(), "application/octet-stream"),
                            headers={"Cache-Control": "public, max-age=31536000, immutable"})

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
                                     done=bool(body.get("done")), hand=str(body.get("hand") or ""))

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
                                     body=str(body.get("body") or ""), reply_to=sheet_id, reply_line=body.get("line"),
                                     hand=str(body.get("hand") or ""))

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
