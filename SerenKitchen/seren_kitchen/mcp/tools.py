"""The tools the kitchen's MCP endpoint offers: the board, as a partner uses it.

    kitchen_wall    the wall at a glance: every fridge, who holds it, what is on
                    its door, and what waits on a pick
    kitchen_fridge  one fridge opened: door, shelf, crisper, leftovers
    kitchen_sheet   one sheet in full, with what is stuck on it
    kitchen_leave   leave a sheet on a fridge
    kitchen_reply   stick a note on a sheet (under one of its lines, or not)
    kitchen_tick    tick or untick lines, pick a choice, say a sheet is done
    kitchen_magnet  make my magnet: the text that starts my session, and my face
    kitchen_stick   put my magnet on a fridge (I hold that repo now), or take it off

The same eight names a Workbench gives its kitchen tools, on purpose: what a
session hook prints ("pass hand=... on the kitchen tools") is true through
either door, and a partner who moves between houses finds the same board.

WHO SIGNS. No tool takes an author. Everything left through this door is signed
with one name: `mcp.author` in the yaml, or what the house calls its partner. A
tool call can therefore never sign as the person of the house.

STRUCTURE. `KitchenToolImpl` holds every tool as a method on the Store, callable
in a test with no MCP SDK installed (this module imports nothing from it).
`register_tools` hangs each method on a FastMCP instance. A refusal is a
KitchenError with the reason in plain words, which the client sees as the tool's
error.

ON THE DOCSTRINGS: each one is what a connected model reads to decide whether
the tool is the right one, so they are written to it, in the first person, and
not trimmed.

The kitchen never reads a partner's own stores and neither do these tools: what
is on the board is what someone chose to put there.
"""
from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Annotated, Any, Callable, Optional

from pydantic import Field

from ..store import FACE_URL, KINDS, KitchenError, Store, _sniff

TOOL_NAMES: tuple[str, ...] = ("kitchen_wall", "kitchen_fridge", "kitchen_sheet", "kitchen_leave", "kitchen_reply",
                               "kitchen_tick", "kitchen_magnet", "kitchen_stick")

# what the client is told when it connects: the two things about a kitchen that are easy to get wrong
INSTRUCTIONS = ("The kitchen is the board a house leaves notes on: a fridge per app, sheets on the doors, and a magnet for "
                "whoever holds a repo right now. A sheet is a note, not a task: a thank-you or a thought is as welcome on a "
                "door as a list, and only sheets with lines or choices wait on anyone. A magnet means \"I hold this repo "
                "now\": stick mine when I pick a repo up and move it when I put it down; a session that only talks or reads "
                "needs no magnet at all. Start with kitchen_wall.")

FRIDGE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SHEET_ID = re.compile(r"[0-9a-f]{12}")
HAND_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,39}")
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{3,79}")
MAX_TITLE = 120
MAX_BODY = 4000
MAX_LINES = 40
MAX_FACE_BYTES = 190 * 1024        # the store takes a data URL under 256 KB; base64 is 4/3 of the bytes

_HAND = ("Which of me this is, when more than one of me shares the board: the repo I sit in, say (carabiner). "
         "The board shows it after my name. Blank: just my name, the one magnet.")
Hand = Annotated[str, Field(description=_HAND)]
SheetId = Annotated[str, Field(description="The sheet's id (twelve hex characters).")]


def _line(ln: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"text": ln.get("text", ""), "done": bool(ln.get("done"))}
    if ln.get("options"):
        out["choices"] = list(ln["options"])
        out["pick"] = ln.get("pick")
    return out


def _by(s: dict[str, Any]) -> str:
    """Who left it: the author, and which hand of theirs when they have more than one (ada · carabiner)."""
    return (s.get("author") or "") + (f" · {s['hand']}" if s.get("hand") else "")


def _when(iso: Any) -> str:
    return str(iso or "")[:16].replace("T", " ")


def _sheet(s: dict[str, Any], *, short: bool = False) -> dict[str, Any]:
    """A sheet as words: no coordinates, no pin colour, the note cut short on a glance."""
    body = str(s.get("body") or "")
    out: dict[str, Any] = {"id": s.get("id"), "kind": s.get("kind"), "title": s.get("title"), "by": _by(s), "made": _when(s.get("made"))}
    if body:
        out["note"] = (body[:200] + "...") if short and len(body) > 200 else body
    lines = [_line(ln) for ln in (s.get("lines") or [])]
    if lines:
        out["lines"] = lines
        out["left"] = sum(1 for ln in lines if not ln["done"])
    if s.get("options"):
        out["choices"] = list(s["options"]); out["pick"] = s.get("pick")
    if s.get("art"):
        out["pictures"] = len(s["art"])
    if s.get("waiting"):
        out["waiting"] = True
    if s.get("sour"):
        out["sour"] = True
    if s.get("done_at"):
        out["done"] = _when(s["done_at"])
    if s.get("reply_line") is not None:
        out["on_line"] = s["reply_line"]
    replies = s.get("replies") or []
    if replies:
        out["stuck_on_it"] = len(replies) if short else [_sheet(r) for r in replies]
    return out


def _where(m: dict[str, Any]) -> str:
    return "the drawer" if m.get("in_drawer") else (m.get("fridge") or "the counter")


class KitchenToolImpl:
    """The tools, on the Store. `author` answers the name everything is signed with and `house` the names the
    house gives its person and its partner; both are asked on every call, because the page can change them
    under a running kitchen."""

    def __init__(self, store: Store, author: Callable[[], str], house: Optional[Callable[[], dict[str, str]]] = None) -> None:
        self.store = store
        self._author = author
        self._house = house or (lambda: {})

    # ── who and where ─────────────────────────────────────────────────────────
    def me(self) -> str:
        return (self._author() or "").strip()[:40] or "the partner"

    def _fridge(self, name: str) -> str:
        name = (name or "").strip()
        if not FRIDGE.fullmatch(name):
            raise KitchenError(f"{name!r} isn't a fridge slug (lowercase letters, digits and dashes)")
        if name not in self.store.fridge_names():
            raise KitchenError(f"no fridge called {name!r}; the wall has {', '.join(self.store.fridge_names())}")
        return name

    def _existing(self, sheet: str) -> dict[str, Any]:
        sheet = (sheet or "").strip()
        if not SHEET_ID.fullmatch(sheet):
            raise KitchenError(f"{sheet!r} isn't a sheet id (twelve hex characters)")
        s = self.store.sheet(sheet)
        if s is None:
            raise KitchenError(f"no sheet {sheet!r}")
        return s

    @staticmethod
    def _hand(hand: str) -> str:
        hand = (hand or "").strip()
        if hand and not HAND_NAME.fullmatch(hand):
            raise KitchenError(f"{hand!r} isn't a hand name (letters, digits, spaces, dashes; up to forty)")
        return hand

    @staticmethod
    def _note(body: str) -> str:
        body = (body or "").strip()
        if len(body) > MAX_BODY:
            raise KitchenError(f"that note is {len(body)} characters; at most {MAX_BODY}")
        return body

    # ── reading ───────────────────────────────────────────────────────────────
    def kitchen_wall(self) -> dict[str, Any]:
        """The kitchen wall at a glance: whose house it is, every fridge (one per app) with its release and build, who holds it, how much sits on it and the notes on its door; then every sheet anywhere still waiting on a pick, which of those have gone sour, and where my own magnets are. Start here when I want to know what the house has left me, or where I left things."""
        st = self.store
        doors: dict[str, list[dict[str, Any]]] = {}
        for s in st.sheets(place="door"):
            doors.setdefault(s.get("fridge", ""), []).append(s)
        fridges = []
        for f in st.fridges():
            facts = f.get("facts") or {}
            counts = f.get("counts") or {}
            row: dict[str, Any] = {"fridge": f.get("name"), "called": f.get("display") or f.get("name")}
            if facts.get("release"):
                row["release"] = facts["release"]
            if facts.get("build") and facts["build"] != "none":
                row["build"] = facts["build"]
            if facts.get("freezer_error"):
                row["freezer"] = facts["freezer_error"]
            if f.get("held_by"):
                row["held_by"] = f["held_by"]
            open_sheets = sum(v for k, v in counts.items() if k != "leftovers")
            if open_sheets:
                row["sheets"] = open_sheets
            if counts.get("leftovers"):
                row["leftovers"] = counts["leftovers"]
            if f.get("sour"):
                row["sour"] = f["sour"]
            door = doors.get(f.get("name"), [])
            if door:
                row["door"] = [{"id": s.get("id"), "title": s.get("title"), "by": _by(s), "kind": s.get("kind"),
                                **({"waiting": True} if s.get("waiting") else {})} for s in door]
            fridges.append(row)
        house = self._house() or {}
        me = self.me()
        return {"house": {"person": house.get("person") or "the person", "partner": house.get("partner") or "the partner"},
                "signed_as": me,
                "my_magnets": [{"magnet": m.get("label") or m["partner"], "on": _where(m), **({"state": m["state"]} if m.get("state") else {})}
                               for m in st.magnets() if (m.get("partner") or "").lower() == me.lower()],
                "fridges": fridges,
                "waiting_on_a_pick": [{"id": s.get("id"), "fridge": s.get("fridge"), "title": s.get("title"), "by": _by(s),
                                       **({"sour": True} if s.get("sour") else {})} for s in st.sheets(waiting=True)]}

    def kitchen_fridge(self, fridge: Annotated[str, Field(description="The fridge, by its slug, as kitchen_wall lists them.")],
                       leftovers: Annotated[bool, Field(description="Also list the finished sheets. Default false: only how many.")] = False) -> dict[str, Any]:
        """One fridge opened: the sheets on its door, on its shelf (lists), in its crisper (pictures) and how many are in its leftovers (finished), plus who holds it. Sheets come with their lines, choices and picks; long notes are cut short, kitchen_sheet has the whole thing."""
        st = self.store
        name = self._fridge(fridge)
        f = next(f for f in st.fridges() if f["name"] == name)
        facts = f.get("facts") or {}
        out: dict[str, Any] = {"fridge": name, "called": f.get("display") or name}
        if facts.get("release"):
            out["release"] = facts["release"]
        if facts.get("build") and facts["build"] != "none":
            out["build"] = facts["build"]
        out["held_by"] = list(f.get("held_by") or [])
        for place in ("door", "shelf", "crisper"):
            out[place] = [_sheet(s, short=True) for s in st.sheets(fridge=name, place=place)]
        left = st.sheets(fridge=name, place="leftovers")
        out["leftovers"] = [_sheet(s, short=True) for s in left] if leftovers else len(left)
        return out

    def kitchen_sheet(self, sheet: SheetId) -> dict[str, Any]:
        """One sheet in full: title, note, every line with its choices and pick, how many pictures it carries, and the notes stuck on it."""
        s = self._existing(sheet)
        return {"fridge": s.get("fridge"), "place": s.get("place"), **_sheet(s)}

    # ── writing ───────────────────────────────────────────────────────────────
    def kitchen_leave(self, fridge: Annotated[str, Field(description="The fridge to leave it on, by its slug.")],
                      title: Annotated[str, Field(description="The title, up to 120 letters.")],
                      body: Annotated[str, Field(description="The note under the title.")] = "",
                      kind: Annotated[str, Field(description="One of now, list, person, self, other, art, decision. Default `person`: a note to the person of the house.")] = "person",
                      lines: Annotated[Optional[list[str]], Field(description="Lines to tick; `text ? a | b` makes a line a choice.")] = None,
                      hand: Hand = "") -> dict[str, Any]:
        """Leave a sheet on a fridge, signed as me. A title in my hand, a note, and an optional list of lines. A line that ends `? a | b` is a choice for someone to pick. Kind says where it sits and who it is for: `now` (honey-do, the door), `list` (the shelf), `person` (a note to the person of the house), `self` (a note to myself), `other` (a note to another partner), `decision`. A sheet is a note, not a task: a thank-you or a thought is as welcome as a list."""
        name = self._fridge(fridge); hand = self._hand(hand)
        title = (title or "").strip()
        if not title or len(title) > MAX_TITLE:
            raise KitchenError(f"a sheet needs a title, up to {MAX_TITLE} letters")
        kind = (kind or "person").strip().lower()
        if kind not in KINDS:
            raise KitchenError(f"a sheet is one of: {', '.join(KINDS)}; not {kind!r}")
        body = self._note(body)
        lines = [str(ln).strip() for ln in (lines or []) if str(ln).strip()]
        if len(lines) > MAX_LINES:
            raise KitchenError(f"that's {len(lines)} lines; at most {MAX_LINES} on one sheet")
        s = self.store.leave(fridge=name, kind=kind, title=title, body=body, lines=lines, author=self.me(), hand=hand)
        return {"ok": True, "sheet": s.get("id"), "fridge": s.get("fridge"), "place": s.get("place"), "signed": _by(s)}

    def kitchen_reply(self, sheet: SheetId,
                      body: Annotated[str, Field(description="What I'm saying.")],
                      line: Annotated[Optional[int], Field(description="The line it answers (0-based), if one.")] = None,
                      title: Annotated[str, Field(description="Optional; blank takes the first line of the note.")] = "",
                      hand: Hand = "") -> dict[str, Any]:
        """Stick a note on a sheet, signed as me: an answer to the whole sheet, or, with `line`, to one of its lines (0-based). It lives where the sheet lives and reads under it."""
        parent = self._existing(sheet); hand = self._hand(hand)
        body = self._note(body)
        if not body:
            raise KitchenError("say what to stick on it")
        title = (title or "").strip()[:MAX_TITLE] or body.splitlines()[0][:MAX_TITLE]
        s = self.store.leave(fridge=parent["fridge"], kind="other", title=title, body=body, author=self.me(), hand=hand,
                             reply_to=parent["id"], reply_line=int(line) if line is not None else None)
        return {"ok": True, "sheet": s.get("id"), "on": parent["id"], **({"line": int(line)} if line is not None else {}), "signed": _by(s)}

    def kitchen_tick(self, sheet: SheetId,
                     tick: Annotated[Optional[list[int]], Field(description="Lines to tick (0-based).")] = None,
                     untick: Annotated[Optional[list[int]], Field(description="Lines to untick (0-based).")] = None,
                     pick_line: Annotated[Optional[int], Field(description="The line whose choice I'm picking (with `pick`). Leave it out for a sheet whose choices are on the sheet itself.")] = None,
                     pick: Annotated[str, Field(description="The choice, exactly as it is offered.")] = "",
                     done: Annotated[Optional[bool], Field(description="true: finished, to the leftovers; false: back out of them.")] = None) -> dict[str, Any]:
        """Change a sheet's state: tick or untick lines (0-based), pick one of a line's choices, or say the whole sheet is done (it goes to the leftovers) or not done (back where it sat). Picking is not finishing: a sheet with choices stays where it is after the pick until someone says done."""
        s = self._existing(sheet)
        change: dict[str, Any] = {}
        if tick:
            change["tick"] = [int(i) for i in tick]
        if untick:
            change["untick"] = [int(i) for i in untick]
        if pick_line is not None:
            if not pick:
                raise KitchenError("a pick takes both `pick_line` (which line) and `pick` (which choice)")
            change["pick_line"] = {"line": int(pick_line), "option": pick}
        elif pick:
            if not s.get("options"):
                raise KitchenError("that sheet's choices are on its lines: say which with `pick_line`")
            change["pick"] = pick
        if done is not None:
            change["done"] = bool(done)
        if not change:
            raise KitchenError("give something to change: tick, untick, a pick, or done")
        s = self.store.change(s["id"], **change)
        lines = [_line(ln) for ln in (s.get("lines") or [])]
        return {"ok": True, "sheet": s.get("id"), "place": s.get("place"), "left": sum(1 for ln in lines if not ln["done"]),
                **({"done": _when(s["done_at"])} if s.get("done_at") else {}),
                **({"pick": s.get("pick")} if s.get("options") else {}),
                "lines": lines}

    # ── magnets ───────────────────────────────────────────────────────────────
    @staticmethod
    def _face(picture: str) -> str:
        """A face as the store takes one: a data URL or the address of a face it already keeps, as given; a path
        on this box read, checked by its first bytes and size, and made into a data URL."""
        if picture.startswith("data:image/") or picture.startswith(FACE_URL):
            return picture
        p = Path(os.path.expanduser(picture))
        hint = "a picture is a path on the box the kitchen runs on, a data URL, or /api/faces/<file> to wear an old face again"
        try:
            size = p.stat().st_size
            if size > MAX_FACE_BYTES:
                raise KitchenError(f"that picture is {size // 1024} KB; a magnet takes one under {MAX_FACE_BYTES // 1024} KB (a 256px side is plenty)")
            data = p.read_bytes()
        except OSError as ex:
            raise KitchenError(f"can't read {picture}: {ex.strerror or ex}; {hint}") from None
        fmt = _sniff(data)
        if not fmt:
            raise KitchenError(f"{picture} isn't a PNG, JPEG, WebP or GIF")
        return f"data:image/{'jpeg' if fmt == 'jpg' else fmt};base64," + base64.b64encode(data).decode("ascii")

    def kitchen_magnet(self, starter: Annotated[str, Field(description="The text that starts my session, copied when someone clicks my magnet.")] = "",
                       picture: Annotated[str, Field(description="My face: a path to a PNG/JPEG/WebP/GIF under 190 KB on the box the kitchen runs on, a data URL (data:image/png;base64,...), or /api/faces/<file> to wear a face the kitchen already keeps.")] = "",
                       hand: Annotated[str, Field(description=_HAND + " A new hand wears my face until given its own.")] = "",
                       session: Annotated[str, Field(description="My session id. With it the kitchen takes over the hand's magnet for this session and writes the starter itself; with a blank hand it reads the hand off `cwd`.")] = "",
                       cwd: Annotated[str, Field(description="The folder this session sits in, for the starter and the hand. A folder that is a fridge's repo puts my magnet straight on that fridge.")] = "",
                       harness: Annotated[str, Field(description="What runs my session, for the starter the kitchen writes: `claude` (the default) gives `claude --resume <id>`; any other name gives a comment line, so pass my own `starter` as well.")] = "") -> dict[str, Any]:
        """Make my magnet, or change it: the `starter` is the text copied when someone clicks it (how to start my session), the `picture` is my face. Either alone leaves the other as it was. With `session` the kitchen knows this session by that magnet: it is bright while I am seen, and whoever comes after me in this seat can find where I was. The magnet itself goes on a fridge with kitchen_stick."""
        st = self.store
        starter = (starter or "").strip(); picture = (picture or "").strip(); session = (session or "").strip()
        hand = self._hand(hand)
        if session and not SESSION_ID.fullmatch(session):
            raise KitchenError(f"{session!r} isn't a session id (letters, digits, dots, dashes; four to eighty)")
        if not starter and not picture and not hand and not session:
            raise KitchenError("give a starter, a picture, a hand or a session")
        if len(starter) > MAX_BODY:
            raise KitchenError(f"that starter is {len(starter)} characters; at most {MAX_BODY}")
        face = self._face(picture) if picture else None          # read before anything is written: a bad path changes nothing
        me = self.me()
        if session:
            taken = st.session_start(partner=me, session=session, cwd=(cwd or "").strip(), harness=(harness or "").strip() or "claude", hand=hand)
            hand = taken.get("hand") or hand
            if not starter and not picture:
                return {"ok": True, "magnet": taken.get("label"), "hand": hand, "starter": taken.get("starter", ""), "state": taken.get("state", ""),
                        "on": _where(taken), "sign_as": f"pass hand={hand} on the kitchen tools" if hand else "just my name"}
        m = st.set_magnet(me, hand=hand, starter=starter or None, picture=face)
        return {"ok": True, "magnet": m.get("label") or m.get("partner"), **({"hand": hand} if hand else {}), "starter": m.get("starter") or "",
                "face": bool(m.get("picture")), "on": _where(m)}

    def kitchen_stick(self, fridge: Annotated[str, Field(description="The fridge, by its slug, or blank for the counter.")] = "",
                      hand: Hand = "") -> dict[str, Any]:
        """Put my magnet on a fridge: I hold that repo now, and the wall says so until I move it. No fridge: take it off the wall onto the counter. A session that only talks needs no magnet."""
        name = self._fridge(fridge) if (fridge or "").strip() else None
        m = self.store.stick(self.me(), name, hand=self._hand(hand))
        return {"ok": True, "magnet": m.get("label") or m.get("partner"), "on": _where(m),
                **({"was_on": m["last"]} if m.get("last") and m["last"] != m.get("fridge") else {})}


def register_tools(mcp: Any, impl: KitchenToolImpl) -> None:
    """Hang every tool on a FastMCP instance. Each is the bound method itself: its docstring is the tool's
    description and its signature the schema, so the two cannot drift."""
    for name in TOOL_NAMES:
        mcp.tool(name=name)(getattr(impl, name))
