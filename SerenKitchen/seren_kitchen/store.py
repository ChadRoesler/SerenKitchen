"""The kitchen's state: one JSON file, written whole and atomically, like a fridge
door that is either closed or open and never half.

WHAT LIVES HERE. Three kinds of thing, and nothing else:

  * facts    what the freezer shows per fridge (latest release, build), set by
             whoever knows (Lodestar, the CI, a person), never looked up here;
  * magnets  one per partner: their picture, the text that starts their
             session, and the fridge they are stuck to right now. A magnet on a
             fridge is who holds that repo. It stays where it was left when the
             session ends, so the next one in sees who was here;
  * sheets   the notes. A sheet is one piece of paper: a title in someone's hand
             and lines under it that can be ticked. A list is one sheet with many
             lines; a thought is a sheet with one. Its kind says where it sits:
             on the door (the glance) or inside on a shelf. A finished sheet goes
             to the leftovers. A decision nobody picks goes sour after a while.

WHY NOT A DATABASE. A kitchen has a few dozen sheets, not a few million; a file
you can open in an editor, back up with cp and read after the service is gone
is worth more than a query planner. Every write replaces the file through a
rename, so a crash mid-write leaves the old kitchen, never a torn one.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Optional

# person: a note to the person of the house; other: a note to the partner (the page puts names on
# these from the house's settings).
KINDS = ("now", "list", "person", "self", "other", "art", "decision")
PLACES = ("door", "shelf", "crisper", "leftovers")
# where a fresh sheet of each kind sits
PLACE_BY_KIND = {"now": "door", "list": "shelf", "person": "door", "self": "door", "other": "door",
                 "art": "crisper", "decision": "door"}
MAX_PICTURE = 256 * 1024          # a magnet's picture, as a data URL
# a magnet's face is a file in <state>/faces named by what is in it, and the magnet carries its address
FACE_TYPES = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "gif": "gif", "webp": "webp"}
FACE_NAME = re.compile(r"[0-9a-f]{16}\.(png|jpg|gif|webp)")
FACE_URL = "/api/faces/"
HISTORY = 12                      # the sessions a magnet remembers carrying before this one
GREY_AFTER_HOURS = 12.0           # Chad, 16 Nov 2026: "12 hours or so is the magnet goes grey,
DRAWER_AFTER_DAYS = 3.0           #   and older than a few days they go to the counter drawer"
BUSY = 3600.0                     # a session that did something within the hour still holds its hand: a new one is -2


def _sniff(data: bytes) -> str:
    """What a picture is by its first bytes, whatever its label says: png, jpg, gif, webp or ''."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def _label(partner: str, hand: str) -> str:
    """How a magnet is keyed and shown: the partner, and the hand when there is one."""
    return f"{partner}·{hand}" if hand else partner


def _starter(harness: str, cwd: str, session: str) -> str:
    """The text copied off a magnet: how to pick that session up again."""
    head = f"cd {cwd}\n" if cwd else ""
    if (harness or "claude") == "claude":
        return head + f"claude --resume {session}"
    return head + f"# {harness} session {session}"


def _epoch(iso: str) -> float:
    try:
        return time.mktime(time.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0
MAX_TEXT = 4000
CLEAR_WINDOW = 300.0              # seconds: a /clear's end and the start that follows it are a second apart; this is slack


def _folder(cwd: str) -> str:
    """The last part of a folder path, whichever box wrote it. A Windows path arriving at a kitchen on Linux has
    backslashes that pathlib there does not split."""
    parts = [p for p in re.split(r"[\\/]+", str(cwd or "")) if p]
    return parts[-1] if parts else ""

# the house's own fridge, when the yaml names none: its sheets go on the big fridge's door and freezer
HOUSE_FRIDGE = "house"
# the first sheet in a new kitchen, on the house's own fridge, so the first door is never bare
HOUSEWARMING = {"kind": "person", "title": "the fridge is ours.",
                "lines": ["don't touch the cheese."], "author": "the kitchen", "pin": "#d0393e"}


_CHOICE = re.compile(r"^(.*?)\s*\?\s*([^|]+\|.+)$")


def _line(item: Any) -> dict[str, Any]:
    """A line of a sheet. A string is its text; `text ? a | b | c` gives the line choices to pick
    from; a dict may carry text, options, done and pick explicitly."""
    if isinstance(item, dict):
        text = str(item.get("text") or "").strip()[:MAX_TEXT]
        opts = [str(o).strip()[:200] for o in (item.get("options") or []) if str(o).strip()]
        ln: dict[str, Any] = {"text": text, "done": bool(item.get("done"))}
        if len(opts) >= 2:
            ln["options"] = opts; ln["pick"] = item.get("pick") if item.get("pick") in opts else None
        return ln
    text = str(item).strip()
    m = _CHOICE.match(text)
    if m:
        opts = [o.strip()[:200] for o in m.group(2).split("|") if o.strip()]
        if len(opts) >= 2:
            return {"text": m.group(1).strip()[:MAX_TEXT], "done": False, "options": opts, "pick": None}
    return {"text": text[:MAX_TEXT], "done": False}


def _lines(items: Optional[Iterable[Any]]) -> list[dict[str, Any]]:
    return [ln for ln in (_line(i) for i in (items or [])) if ln["text"]]


def _waiting(s: dict[str, Any]) -> bool:
    """Something on this sheet is waiting on a pick: a line with choices and none taken, or an old-style
    decision sheet with options and no pick."""
    if s.get("done_at"):
        return False
    if any(ln.get("options") and not ln.get("pick") for ln in s.get("lines", [])):
        return True
    return bool(s.get("kind") == "decision" and s.get("options") and not s.get("pick"))


def _now() -> float:
    return time.time()


def _iso(t: Optional[float]) -> Optional[str]:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t)) if t else None


class KitchenError(ValueError):
    """A request the kitchen refuses, with the reason in plain words (a 400 upstairs)."""


class Store:
    def __init__(self, path: Path, fridges: list[dict[str, Any]], sour_after_days: float = 7.0,
                 grey_after_hours: float = GREY_AFTER_HOURS, drawer_after_days: float = DRAWER_AFTER_DAYS,
                 house_fridge: str = HOUSE_FRIDGE, trim_prefix: str = ""):
        self.path = Path(path)
        # the fridge that is the house itself (the big fridge), and a prefix every fridge of this house shares that a
        # hand leaves off (fridge acme-billing, prefix acme-: hand billing). Neither names anything by default.
        self.house_fridge = (house_fridge or HOUSE_FRIDGE).strip()
        self.trim_prefix = (trim_prefix or "").strip().lower()
        self.sour_after = float(sour_after_days) * 86400.0
        # a magnet's life (the house can change both from the page): bright while its session was seen within
        # grey_after, grey after that or once it ends, in the drawer once quiet past drawer_after
        self.grey_after = float(grey_after_hours) * 3600.0
        self.drawer_after = float(drawer_after_days) * 86400.0
        # a session that starts in a folder that IS a fridge's repo holds that repo from its first minute
        self.stick_on_start = True
        self._fridges = {f["name"]: dict(f) for f in fridges}
        self.faces_dir = self.path.parent / "faces"
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {"facts": {}, "magnets": {}, "sheets": {}, "faces": {}}
        self._load()

    # ── the file ──────────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in ("facts", "magnets", "sheets", "faces"):
                    v = raw.get(key)
                    self._data[key] = v if isinstance(v, dict) else {}
                # a magnet from before hands is the partner's only hand
                for m in self._data["magnets"].values():
                    m.setdefault("hand", ""); m.setdefault("label", m.get("partner", ""))
                # a sheet's pictures are a list, whatever an older file said
                for s in self._data["sheets"].values():
                    if isinstance(s.get("art"), str):
                        s["art"] = [s["art"]]
                    elif not isinstance(s.get("art"), list):
                        s["art"] = []
                # a face kept inside the file as a data URL (before 16 Nov 2026) moves out to a file of its own,
                # and goes in the gallery as the face that magnet has worn since it was made
                moved = False
                for m in self._data["magnets"].values():
                    pic = m.get("picture") or ""
                    if pic.startswith("data:image/"):
                        try:
                            name = self._keep_face(pic)
                        except (KitchenError, OSError):
                            # an unreadable face, or a disk that would not take it, stays as it was: never let a
                            # face's move send the whole kitchen to .unreadable below
                            continue
                        m["picture"] = FACE_URL + name
                        self._hang_face(m, name, when=m.get("since"))
                        moved = True
                if self._collapse_faces() or moved:
                    self._save()
                return
        except FileNotFoundError:
            pass
        except (OSError, ValueError):
            # a half-written or corrupt file: start empty rather than crash; the old file is kept beside
            try:
                os.replace(self.path, self.path.with_suffix(".json.unreadable"))
            except OSError:
                pass
        # a brand-new kitchen gets its housewarming note, on the house's own fridge
        if not self._data["sheets"] and self.house_fridge in self._fridges:
            self._leave(fridge=self.house_fridge, **HOUSEWARMING)
            self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ── fridges and their freezer facts ───────────────────────────────────────
    def fridge_names(self) -> list[str]:
        return list(self._fridges)

    def move_sheets(self, src: str, dst: str) -> int:
        """Every sheet kept for `src` (on the wall or not), the notes stuck on them with them, onto `dst`, where
        they sit as they sat. How many moved, replies counted."""
        self._need_fridge(dst)
        if src == dst:
            raise KitchenError("a fridge's sheets are already on it")
        with self._lock:
            moved = [s for s in self._data["sheets"].values() if s.get("fridge") == src]
            now = _iso(_now())
            for s in moved:
                s["fridge"] = dst; s["updated"] = now
            if moved:
                self._save()
            return len(moved)

    def set_down_from(self, fridge: str) -> list[str]:
        """Every magnet on that fridge back onto the counter, remembering it as where it was. Their labels."""
        with self._lock:
            down = [m for m in self._data["magnets"].values() if m.get("fridge") == fridge]
            now = _iso(_now())
            for m in down:
                m.update(fridge=None, last=fridge, since=now)
            if down:
                self._save()
            return [m["label"] for m in down]

    def kept_for(self, fridge: str) -> int:
        """How many sheets (replies counted) are kept for that fridge, on the wall or not."""
        return sum(1 for s in self._data["sheets"].values() if s.get("fridge") == fridge)

    def off_the_wall(self) -> dict[str, int]:
        """Sheets kept for a fridge that is not on the wall now, by fridge. They are never thrown out: they come
        back the moment their fridge does (a yaml that lost its fridges on an upgrade, a fridge hidden from the page)."""
        out: dict[str, int] = {}
        for s in self._data["sheets"].values():
            if s.get("fridge") not in self._fridges and not s.get("reply_to"):
                out[s.get("fridge") or ""] = out.get(s.get("fridge") or "", 0) + 1
        return out

    def set_fridges(self, fridges: list[dict[str, Any]]) -> None:
        """The wall changed from the page (a fridge added, hidden or reordered): sheets on a fridge that is
        gone stay in the file and come back the moment it does."""
        with self._lock:
            self._fridges = {f["name"]: dict(f) for f in fridges}

    def _need_fridge(self, name: str) -> dict[str, Any]:
        f = self._fridges.get(name)
        if f is None:
            raise KitchenError(f"no fridge called {name!r}; the wall has {', '.join(self._fridges)}")
        return f

    def fridges(self) -> list[dict[str, Any]]:
        out = []
        for name, f in self._fridges.items():
            counts = {p: 0 for p in PLACES}
            sour = 0
            for s in self._data["sheets"].values():
                if s.get("fridge") == name:
                    counts[s.get("place", "door")] += 1
                    if self._is_sour(s):
                        sour += 1
            holders = [m.get("label") or m["partner"] for m in self._data["magnets"].values()
                       if m.get("fridge") == name and not self._in_drawer(m, self._state(m))]
            out.append({**f, "facts": dict(self._data["facts"].get(name) or {}), "counts": counts, "sour": sour,
                        "held_by": holders})
        return out

    def set_facts(self, name: str, **facts: Any) -> dict[str, Any]:
        self._need_fridge(name)
        with self._lock:
            cur = dict(self._data["facts"].get(name) or {})
            for k, v in facts.items():
                if v is None:
                    cur.pop(k, None)
                else:
                    cur[k] = str(v)[:200]
            cur["checked_at"] = _iso(_now())
            self._data["facts"][name] = cur
            self._save()
        return cur

    # ── faces: the pictures magnets wear, kept as files, and the gallery of them ─
    def _keep_face(self, picture: str) -> str:
        """A face given as a data URL, written to <state>/faces as a file named by what is in it (the same
        picture twice is one file). Returns the file's name."""
        head, _, b64 = picture.partition(",")
        if not head.startswith("data:image/") or ";base64" not in head:
            raise KitchenError("the picture is a data URL of an image (data:image/png;base64,...)")
        try:
            data = base64.b64decode(b64, validate=True)
        except (binascii.Error, ValueError):
            raise KitchenError("that picture's data URL is not readable base64") from None
        ext = _sniff(data)
        if not ext:
            raise KitchenError("a face is a PNG, JPEG, GIF or WebP")
        name = f"{hashlib.sha256(data).hexdigest()[:16]}.{ext}"
        p = self.faces_dir / name
        if not p.is_file():
            self.faces_dir.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, p)
        return name

    def _fridge_for_hand(self, hand: str) -> Optional[str]:
        """The fridge a hand is named after (billing and billing-2 are acme-billing's, with the prefix acme-), when
        there is one."""
        base = re.sub(r"-\d+$", "", (hand or "").strip().lower())
        for name in ((self.trim_prefix + base) if self.trim_prefix else "", base):
            if base and name in self._fridges:
                return name
        return None

    def _hang_face(self, m: dict[str, Any], name: str, when: Optional[str] = None) -> dict[str, Any]:
        """A magnet put on a face: it goes in the gallery, under the fridge the magnet is on (or the one its
        hand is named after), and the face it wore before is marked as worn until now. A picture hangs once
        per fridge: one already there is taken down from 'until' rather than hung twice (16 Nov 2026: the
        move out of the json hung one face twelve times, once per hand wearing it)."""
        now = _iso(_now())
        fridge = m.get("fridge") or self._fridge_for_hand(m.get("hand", ""))
        for f in self._data["faces"].values():
            if f.get("label") == m["label"] and not f.get("until") and f.get("file") != name:
                f["until"] = now
        same = next((f for f in self._data["faces"].values() if f.get("file") == name and f.get("fridge") == fridge), None)
        if same is not None:
            same["until"] = None
            return same
        fid = uuid.uuid4().hex[:12]
        f = self._data["faces"][fid] = {"id": fid, "file": name, "partner": m["partner"], "hand": m.get("hand", ""), "label": m["label"],
                                         "fridge": fridge, "made": str(when or now)[:19], "until": None}
        return f

    def _collapse_faces(self) -> bool:
        """One picture, one place in the gallery per fridge: the first time it was hung there, still open if any
        of its copies was. True when something collapsed."""
        keep: dict[tuple, dict[str, Any]] = {}
        gone = []
        for fid, f in sorted(self._data["faces"].items(), key=lambda kv: kv[1].get("made") or ""):
            k = (f.get("file"), f.get("fridge") or "")
            if k not in keep:
                keep[k] = f
                continue
            first = keep[k]
            if not f.get("until") or not first.get("until"):
                first["until"] = None
            else:
                first["until"] = max(first["until"], f["until"])
            gone.append(fid)
        for fid in gone:
            self._data["faces"].pop(fid, None)
        return bool(gone)

    def _face_view(self, f: dict[str, Any]) -> dict[str, Any]:
        url = FACE_URL + f["file"]
        wearing = sorted(m["label"] for m in self._data["magnets"].values() if m.get("picture") == url)
        return {**f, "url": url, "wearing": wearing}

    def faces(self, fridge: Optional[str] = None) -> list[dict[str, Any]]:
        """Every face a magnet has worn, newest first. `fridge`: the ones hung on that fridge; "" the ones
        that belong to no fridge (made on the counter by a hand with no fridge of its own)."""
        out = [(f.get("made") or "", i, self._face_view(f)) for i, f in enumerate(self._data["faces"].values())
               if fridge is None or (f.get("fridge") or "") == fridge]
        out.sort(key=lambda t: t[:2], reverse=True)          # two faces in the same second: the later one hung first
        return [f for _, _, f in out]

    def face_file(self, name: str) -> Optional[Path]:
        if not FACE_NAME.fullmatch(name or ""):
            return None
        p = self.faces_dir / name
        return p if p.is_file() else None

    def drop_face(self, face_id: str) -> bool:
        """A face out of the gallery. The file goes when nothing else names it: no other entry, and no magnet
        wearing it (a magnet keeps its face; the gallery only forgets that it was hung)."""
        with self._lock:
            f = self._data["faces"].pop(face_id, None)
            if f is None:
                return False
            url = FACE_URL + f["file"]
            still = any(x.get("file") == f["file"] for x in self._data["faces"].values()) or \
                any(m.get("picture") == url for m in self._data["magnets"].values())
            if not still:
                try:
                    (self.faces_dir / f["file"]).unlink()
                except OSError:
                    pass
            self._save()
            return True

    # ── magnets ───────────────────────────────────────────────────────────────
    def magnets(self) -> list[dict[str, Any]]:
        return [self._magnet_view(m) for m in self._data["magnets"].values()]

    def magnet(self, partner: str, hand: str = "") -> Optional[dict[str, Any]]:
        m = self._data["magnets"].get(_label(partner, hand))
        return self._magnet_view(m) if m else None

    # ── sessions on magnets ───────────────────────────────────────────────────
    def fridge_for_folder(self, cwd: str) -> Optional[str]:
        """The fridge whose repo that folder is (D:/x/AcmeBilling is the fridge whose repo is someone/AcmeBilling),
        or None."""
        folder = _folder(cwd)
        for f in self._fridges.values():
            repo = str(f.get("repo") or "")
            if folder and repo.rsplit("/", 1)[-1].lower() == folder.lower():
                return f["name"]
        return None

    def hand_for(self, cwd: str) -> str:
        """The hand a session in that folder is, when it names none: the fridge whose repo the folder is
        named after, without the house's prefix when it has one (acme-billing, prefix acme-: billing); else the
        folder's name."""
        name = self.fridge_for_folder(cwd)
        if name:
            p = self.trim_prefix
            return name[len(p):] if p and name.lower().startswith(p) and len(name) > len(p) else name
        return re.sub(r"[^a-z0-9-]+", "-", _folder(cwd).lower()).strip("-")[:40]

    def _state(self, m: dict[str, Any]) -> str:
        """What a magnet with a session is doing: live (seen within grey_after, 12 hours), idle (quieter than
        that: grey), ended (its session said it ended: grey), missing (ended or unseen past drawer_after,
        3 days: in the drawer). A magnet made by hand, with no session, has no state. A closed tab never says
        it ended, which is why time does the work and an /exit is never needed."""
        now = _now()
        if m.get("ended_at"):
            return "missing" if now - _epoch(m["ended_at"]) > self.drawer_after else "ended"
        if not m.get("session"):
            return ""
        age = now - _epoch(m.get("seen") or m.get("since") or "")
        return "live" if age < self.grey_after else ("idle" if age < self.drawer_after else "missing")

    def _touch(self, partner: str, hand: str) -> None:
        """A hand did something on the board: its magnet was seen now."""
        m = self._data["magnets"].get(_label((partner or "").strip(), (hand or "").strip()[:40]))
        if m is not None and m.get("session"):
            m["seen"] = _iso(_now())

    def session_start(self, *, partner: str, session: str, cwd: str = "", harness: str = "claude", box: str = "",
                      source: str = "", hand: str = "") -> dict[str, Any]:
        """A session began: the hand's magnet is made or taken over (session, folder and starter replaced,
        the old id kept as `previous`), never stuck anywhere by this. If another session of the same
        partner is live under that hand, this one is the next number (carabiner-2).

        When no hand is named: a session the kitchen already knows keeps its magnet, from whatever folder
        it was resumed in (the kitchen hand resumed from the parent folder is still the kitchen hand); and a
        start that Claude Code calls `clear` is the same seat with a new transcript, so it takes the magnet
        whose session just ended that way in this folder on this box. Only then is the hand read off the
        folder."""
        partner = (partner or "").strip(); session = (session or "").strip()[:80]
        if not partner or not session:
            raise KitchenError("a session needs a partner and a session id")
        hand = (hand or "").strip()[:40]
        with self._lock:
            if not hand:
                mine = [x for x in self._data["magnets"].values() if x.get("partner") == partner]
                found = next((x for x in mine if x.get("session") == session), None)
                if found is None and (source or "").strip().lower() == "clear":
                    now = _now()
                    cleared = [x for x in mine if x.get("ended_at") and x.get("end_reason") == "clear"
                               and now - _epoch(x["ended_at"]) < CLEAR_WINDOW and x.get("cwd") == str(cwd or "")[:300]
                               and (not box or not x.get("box") or x.get("box") == str(box or "")[:60])]
                    found = max(cleared, key=lambda x: x["ended_at"]) if cleared else None
                hand = found.get("hand", "") if found is not None else self.hand_for(cwd)
            base = hand
            for k in range(2, 9):
                m = self._data["magnets"].get(_label(partner, hand))
                # BUSY, not bright: another session holds this hand only if it did something within the hour. A tab
                # closed this morning still looks bright for twelve hours, and must not turn every new tab in that
                # folder into a numbered stranger; the new session takes the hand over instead.
                if m is None or not m.get("session") or m["session"] == session or not self._busy(m):
                    break
                hand = f"{base}-{k}"
            if self._data["magnets"].get(_label(partner, hand)) is None:
                self.set_magnet(partner, hand=hand)
            m = self._data["magnets"][_label(partner, hand)]
            if m.get("session") and m["session"] != session:
                m["previous"] = m["session"]
                # the session it carried until now, kept on the magnet with its starter and the face it wore then,
                # so an old seat can still be found and picked up again from the drawer
                was = {k: m.get(k) for k in ("session", "cwd", "box", "harness", "starter", "since", "seen", "ended_at", "end_reason", "picture")}
                m["history"] = ([was] + [h for h in (m.get("history") or []) if h.get("session") != session])[:HISTORY]
            m.update(session=session, cwd=str(cwd or "")[:300], harness=(harness or "claude")[:20], box=str(box or "")[:60],
                     source=str(source or "")[:20], seen=_iso(_now()), ended_at=None, end_reason="", drawer=None)
            m["starter"] = _starter(m["harness"], m["cwd"], session)[:MAX_TEXT]
            # STICK ON START (Chad, 16 Nov 2026): a session in a folder that is a fridge's repo holds it from its first
            # minute, rather than relying on a model remembering kitchen_stick. Whoever of the same partner held it
            # moves to the counter, and this session is told who that was and whether they are still at work there.
            took: list[dict[str, Any]] = []
            fridge = self.fridge_for_folder(cwd) if self.stick_on_start else None
            if fridge and m.get("fridge") != fridge:
                took = [{"label": x["label"], "state": self._state(x), "busy": self._busy(x)} for x in self._data["magnets"].values()
                        if x is not m and x.get("partner") == partner and x.get("fridge") == fridge and not self._in_drawer(x, self._state(x))]
                self.stick(partner, fridge, hand=hand)
            self._save()
            return {**self._magnet_view(m), "numbered_from": base if hand != base else "", "stuck": fridge or "", "took_from": took}

    def _busy(self, m: dict[str, Any]) -> bool:
        """Did this magnet's session do something within the hour (and not end)? Busy, not bright: see BUSY."""
        return bool(m.get("session")) and not m.get("ended_at") and _now() - _epoch(m.get("seen") or m.get("since") or "") < BUSY

    def touch(self, *, partner: str, session: str, hand: str = "") -> tuple[Optional[dict[str, Any]], str]:
        """A session is still at work (a prompt was sent in it): its magnet is seen now. Answers (the magnet, what to
        tell the session). The telling is the point: a session whose fridge another hand took, or whose hand a newer
        session took over, learns it the next time it is spoken to, once, instead of working on as a stranger.
        (None, "") when the kitchen has never heard of the session."""
        partner = (partner or "").strip(); session = (session or "").strip()[:80]
        if not partner or not session:
            return None, ""
        with self._lock:
            mine = [x for x in self._data["magnets"].values() if x.get("partner") == partner]
            m = next((x for x in mine if x.get("session") == session), None)
            if m is not None:
                m["seen"] = _iso(_now())
                note = ""
                if m.get("taken_over_by") and not m.get("fridge") and m.get("told_taken_over") != m.get("taken_over_at"):
                    who = self._data["magnets"].get(m["taken_over_by"])
                    still = " and is still at work there" if who is not None and self._busy(who) else ""
                    note = (f"While you were away, {m['taken_over_by']} took {m.get('last')} at {str(m.get('taken_over_at') or '')[11:16]}{still}; "
                            f"your magnet ({m['label']}) is on the counter. Before you touch that repo again, check the kitchen or "
                            f"leave them a note there; kitchen_stick takes it back if it is yours again.")
                    m["told_taken_over"] = m.get("taken_over_at")
                self._save()
                return self._magnet_view(m), note
            # no magnet carries it now: a newer session took its hand over while it was quiet
            for x in mine:
                for h in x.get("history") or []:
                    if h.get("session") == session:
                        if h.get("told"):
                            return self._magnet_view(x), ""
                        h["told"] = _iso(_now())
                        self._save()
                        busy = " It is at work right now." if self._busy(x) else ""
                        return self._magnet_view(x), (
                            f"This session's magnet ({x['label']}) was taken over by a newer session ({x.get('session')}) "
                            f"while this one was quiet.{busy} The kitchen no longer counts this session as holding "
                            f"{x.get('fridge') or 'anything'}: check the kitchen, or leave the other one a note, before working on.")
            return None, ""

    def session_end(self, *, partner: str, session: str, reason: str = "", hand: str = "") -> Optional[dict[str, Any]]:
        """A session ended: every magnet carrying it is marked ended, with the reason (an older kitchen could
        leave one session on two magnets; marking the first and leaving the other live made the /clear that
        followed a numbered stranger, 10 Nov 2026). They stay where they are, saying who was last here. The
        one answered is the named hand's, else one on a fridge. None when no magnet carries that session."""
        partner = (partner or "").strip(); session = (session or "").strip()[:80]
        with self._lock:
            carriers = [x for x in self._data["magnets"].values()
                        if x.get("partner") == partner and session and x.get("session") == session]
            if not carriers:
                return None
            when = _iso(_now()); why = str(reason or "")[:40]
            for x in carriers:
                x["ended_at"] = when; x["end_reason"] = why
            self._save()
            key = _label(partner, (hand or "").strip()[:40])
            m = next((x for x in carriers if x.get("label") == key), None) or next((x for x in carriers if x.get("fridge")), carriers[0])
            return self._magnet_view(m)

    def _in_drawer(self, m: dict[str, Any], state: str) -> bool:
        """The drawer under the counter holds the magnets nobody has used in days (missing), from a fridge or
        from the counter, and any magnet put away by hand. Grey is not gone: a quiet or ended magnet stays
        where it was, on its fridge saying who was last here, or on the counter where a takeover moved it.
        A magnet in the drawer still remembers its fridge, so a session picked up again goes straight back
        to it (unless another hand took the fridge meanwhile: then it was moved to the counter). Taking one
        out by hand keeps it out until its next session."""
        if m.get("drawer") is not None:
            return bool(m["drawer"])
        return state == "missing"

    def _magnet_view(self, m: dict[str, Any]) -> dict[str, Any]:
        state = self._state(m)
        return {**m, "state": state, "in_drawer": self._in_drawer(m, state)}

    def set_magnet(self, partner: str, *, hand: str = "", starter: Optional[str] = None, picture: Optional[str] = None) -> dict[str, Any]:
        """A partner's magnet, or one of them: `hand` tells two of the same partner apart,
        and each hand is its own magnet with its own starter. A new hand wears the face the partner
        already has on another magnet, until it is given one.

        `picture` is a data URL (written to <state>/faces and hung in the gallery), the address of a face
        the kitchen already keeps (/api/faces/<file>: an old face worn again), or "" for none."""
        partner = (partner or "").strip(); hand = (hand or "").strip()[:40]
        if not partner or len(partner) > 40:
            raise KitchenError("a magnet needs a name, forty letters or fewer")
        key = _label(partner, hand)
        face: Optional[str] = None
        if picture:
            if picture.startswith(FACE_URL):
                face = picture[len(FACE_URL):]
                if self.face_file(face) is None:
                    raise KitchenError(f"the kitchen keeps no face called {face!r}")
            elif not picture.startswith("data:image/") or len(picture) > MAX_PICTURE:
                raise KitchenError("the picture is a data URL of an image, under 256 KB")
        with self._lock:
            if picture and face is None:
                face = self._keep_face(picture)
            m = self._data["magnets"].get(key)
            if m is None:
                worn = next((x.get("picture") for x in self._data["magnets"].values() if x.get("partner") == partner and x.get("picture")), "")
                m = self._data["magnets"][key] = {"partner": partner, "hand": hand, "label": key, "starter": "", "picture": worn,
                                                   "fridge": None, "x": 14, "y": 12, "since": _iso(_now())}
            if starter is not None:
                m["starter"] = str(starter)[:MAX_TEXT]
            if picture is not None:
                url = FACE_URL + face if face else ""
                if url and url != m.get("picture"):
                    self._hang_face(m, face)
                elif not url:
                    for f in self._data["faces"].values():
                        if f.get("label") == key and not f.get("until"):
                            f["until"] = _iso(_now())
                m["picture"] = url
            self._save()
            return self._magnet_view(m)

    def put_away(self, partner: str, away: bool, hand: str = "") -> dict[str, Any]:
        """Into the drawer (off whatever fridge it was on, which it remembers as `last`), or out of it onto the
        counter."""
        key = _label((partner or "").strip(), (hand or "").strip()[:40])
        with self._lock:
            m = self._data["magnets"].get(key)
            if m is None:
                raise KitchenError(f"no magnet called {key!r}")
            if away and m.get("fridge"):
                m["last"] = m["fridge"]; m["fridge"] = None; m["since"] = _iso(_now())
            m["drawer"] = bool(away)
            self._save()
            return self._magnet_view(m)

    def stick(self, partner: str, fridge: Optional[str], x: Optional[float] = None, y: Optional[float] = None,
              hand: str = "") -> dict[str, Any]:
        """Stick a magnet to a fridge (that partner holds that repo now), or take it off (fridge None: it
        sits on the counter). Where it was before is remembered on the magnet as `last`."""
        if fridge is not None:
            self._need_fridge(fridge)
        key = _label((partner or "").strip(), (hand or "").strip()[:40])
        with self._lock:
            m = self._data["magnets"].get(key)
            if m is None:
                self.set_magnet(partner, hand=hand)
                m = self._data["magnets"][key]
            now = _iso(_now())
            if m.get("fridge") != fridge:
                m["last"] = m.get("fridge")
                m["since"] = now
            if m.get("session"):
                m["seen"] = now
            if fridge:
                # TAKEN OVER: another hand of the same partner already on this fridge moves to the counter, saying
                # who took it, so a tangle of one partner's sessions never fights over one repo. Another partner on
                # the same fridge (the person of the house beside a partner) is pairing, not a takeover: it stays.
                for other in self._data["magnets"].values():
                    if other is not m and other.get("partner") == m["partner"] and other.get("fridge") == fridge:
                        other.update(fridge=None, last=fridge, since=now, taken_over_by=key, taken_over_at=now)
                m.pop("taken_over_by", None); m.pop("taken_over_at", None)
            m["fridge"] = fridge
            m["drawer"] = None                                 # stuck or set down, it is out of the drawer
            if fridge:
                # a face hung on the counter belongs to the first fridge its magnet is stuck to
                for f in self._data["faces"].values():
                    if f.get("label") == key and not f.get("until") and not f.get("fridge"):
                        f["fridge"] = fridge
            if x is not None:
                m["x"] = float(x)
            if y is not None:
                m["y"] = float(y)
            self._save()
            return self._magnet_view(m)

    def drop_magnet(self, partner: str, hand: str = "") -> bool:
        """Off the board for good. The faces it wore stay in the gallery: a picture someone made of
        themselves is not thrown out with the magnet."""
        with self._lock:
            key = _label(partner, hand)
            gone = self._data["magnets"].pop(key, None) is not None
            if gone:
                for f in self._data["faces"].values():
                    if f.get("label") == key and not f.get("until"):
                        f["until"] = _iso(_now())
                self._save()
            return gone

    # ── sheets ────────────────────────────────────────────────────────────────
    def _is_sour(self, s: dict[str, Any]) -> bool:
        """Milk goes off: something waiting on a pick, older than the bar."""
        return _waiting(s) and (_now() - float(s.get("made_t") or _now())) > self.sour_after

    def _view(self, s: dict[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in s.items() if not k.endswith("_t")}
        out["sour"] = self._is_sour(s)
        out["waiting"] = _waiting(s)
        out["open_lines"] = sum(1 for ln in s.get("lines", []) if not ln.get("done"))
        # a sheet stuck to this one (a reply): shown under it, never on its own
        out["replies"] = [self._view(r) for r in self._data["sheets"].values() if r.get("reply_to") == s["id"]]
        out["replies"].sort(key=lambda r: r.get("made") or "")
        return out

    def sheet(self, sheet_id: str) -> Optional[dict[str, Any]]:
        s = self._data["sheets"].get(sheet_id)
        return self._view(s) if s else None

    def sheets(self, *, fridge: Optional[str] = None, kind: Optional[str] = None, place: Optional[str] = None,
               open_only: bool = False, author: Optional[str] = None, replies: bool = False,
               waiting: bool = False) -> list[dict[str, Any]]:
        """The sheets that match. Replies ride under their parent (`replies` on the view) and are left out
        of the list itself unless asked for. `waiting`: only sheets with a pick nobody has made. A sheet kept for a
        fridge that is not on the wall (hidden, or gone from the yaml) is left out: it waits, unread, until its
        fridge is back (off_the_wall counts them)."""
        out = []
        for s in self._data["sheets"].values():
            if s.get("fridge") not in self._fridges:
                continue
            if s.get("reply_to") and not replies:
                continue
            if waiting and not _waiting(s):
                continue
            if fridge and s.get("fridge") != fridge:
                continue
            if kind and s.get("kind") != kind:
                continue
            if place and s.get("place") != place:
                continue
            if author and (s.get("author") or "").strip().lower() != author.strip().lower():
                continue
            if open_only and s.get("done_at"):
                continue
            out.append(self._view(s))
        out.sort(key=lambda s: s.get("made") or "", reverse=True)
        return out

    def _leave(self, fridge: str, kind: str, title: str, lines: Optional[Iterable[str]] = None, author: str = "",
               pin: str = "", options: Optional[Iterable[str]] = None, place: Optional[str] = None,
               x: Optional[float] = None, y: Optional[float] = None, rot: Optional[float] = None,
               body: str = "", reply_to: Optional[str] = None, reply_line: Optional[int] = None,
               ref: str = "", made: Optional[str] = None, done: bool = False, hand: str = "") -> dict[str, Any]:
        if reply_to:
            parent = self._data["sheets"].get(reply_to)
            if parent is None:
                raise KitchenError(f"no sheet {reply_to!r} to stick this to")
            fridge = parent["fridge"]                        # a reply lives where its parent lives
            if reply_line is not None and not (0 <= int(reply_line) < len(parent.get("lines", []))):
                raise KitchenError(f"that sheet has no line {reply_line}")
        self._need_fridge(fridge)
        if kind not in KINDS:
            raise KitchenError(f"a sheet is one of {', '.join(KINDS)}, not {kind!r}")
        ls = _lines(lines)
        body = str(body or "")[:MAX_TEXT * 4]
        title = (title or "").strip()
        if not title:
            # no title: the first line of the note stands in, then the first list line; a bare sheet is refused
            first = next((t for t in (body.strip().splitlines() + [ln["text"] for ln in ls]) if t.strip()), "")
            title = first.strip()[:60]
        if not title:
            raise KitchenError("a sheet needs a title, a note or a line: something to read")
        if len(title) > 120:
            raise KitchenError("a title is up to 120 letters")
        opts = [str(o).strip()[:200] for o in (options or []) if str(o).strip()]
        if kind == "decision" and len(opts) < 2 and not any(ln.get("options") for ln in ls):
            raise KitchenError("a decision needs choices: options on the sheet, or a line like 'which? a | b'")
        if place is not None and place not in PLACES:
            raise KitchenError(f"a sheet sits on the {', the '.join(PLACES)}; not {place!r}")
        n = len(self._data["sheets"])
        sid = uuid.uuid4().hex[:12]
        t = _now()
        s = {"id": sid, "fridge": fridge, "kind": kind, "title": title,
             "lines": ls,
             "body": body, "art": [],
             "author": (author or "").strip()[:40], "hand": (hand or "").strip()[:40], "pin": pin or "", "place": place or PLACE_BY_KIND[kind],
             "x": float(x) if x is not None else 10 + (n * 37) % 45, "y": float(y) if y is not None else 60 + (n * 53) % 120,
             "rot": float(rot) if rot is not None else -4 + (n * 7) % 9,
             "made": str(made)[:19] if made else _iso(t), "made_t": t, "updated": _iso(t), "done_at": None,
             "reply_to": reply_to or None, "reply_line": int(reply_line) if reply_line is not None else None,
             "ref": str(ref or "")[:80]}
        if kind == "decision":
            s["options"] = opts; s["pick"] = None
        if done:
            s["done_at"] = s["made"]; s["place"] = "leftovers"
        self._data["sheets"][sid] = s
        return s

    def leave(self, **kw: Any) -> dict[str, Any]:
        with self._lock:
            s = self._leave(**kw)
            if kw.get("hand"):
                self._touch(kw.get("author", ""), kw["hand"])
            self._save()
            return self._view(s)

    def change(self, sheet_id: str, **ch: Any) -> dict[str, Any]:
        """title, add_lines, lines (replace all), tick/untick (line indexes), place, x, y, rot,
        done (True: to the leftovers; False: back to where its kind sits), pick (a decision's option),
        pin, fridge (move it to another door)."""
        with self._lock:
            s = self._data["sheets"].get(sheet_id)
            if s is None:
                raise KitchenError(f"no sheet {sheet_id!r}")
            if "title" in ch:
                title = str(ch["title"]).strip()
                if not title or len(title) > 120:
                    raise KitchenError("a sheet needs a title, up to 120 letters")
                s["title"] = title
            if "fridge" in ch:
                self._need_fridge(str(ch["fridge"])); s["fridge"] = str(ch["fridge"])
            if "lines" in ch:
                s["lines"] = _lines(ch["lines"])
            s["lines"].extend(_lines(ch.get("add_lines")))
            if "pick_line" in ch:
                # {"line": i, "option": "b"}: a pick on one line; the line is done with it
                pl = ch["pick_line"] if isinstance(ch["pick_line"], dict) else {}
                try:
                    ln = s["lines"][int(pl.get("line"))]
                except (IndexError, ValueError, TypeError):
                    raise KitchenError(f"no line {pl.get('line')} on that sheet") from None
                if not ln.get("options"):
                    raise KitchenError("that line has no choices on it")
                if pl.get("option") not in ln["options"]:
                    raise KitchenError(f"the pick is one of: {', '.join(ln['options'])}")
                ln["pick"] = pl["option"]; ln["done"] = True; ln["at"] = _iso(_now())
            for key, val in (("tick", True), ("untick", False)):
                for i in ch.get(key) or []:
                    try:
                        s["lines"][int(i)]["done"] = val
                        s["lines"][int(i)]["at" if val else "undone_at"] = _iso(_now())
                    except (IndexError, ValueError, TypeError):
                        raise KitchenError(f"no line {i} on that sheet") from None
            if "pin" in ch:
                s["pin"] = str(ch["pin"] or "")
            if "body" in ch:
                s["body"] = str(ch["body"] or "")[:MAX_TEXT * 4]
            if "art" in ch:
                # the file names of the pictures kept beside the store (the app writes the files; these are the pointers)
                art = ch["art"] or []
                s["art"] = [str(a) for a in (art if isinstance(art, list) else [art]) if a]
            for key in ("x", "y", "rot"):
                if key in ch and ch[key] is not None:
                    s[key] = float(ch[key])
            if "place" in ch:
                if ch["place"] not in PLACES:
                    raise KitchenError(f"a sheet sits on the {', the '.join(PLACES)}; not {ch['place']!r}")
                s["place"] = ch["place"]
            if "pick" in ch:
                if s.get("kind") != "decision":
                    raise KitchenError("only a decision takes a pick")
                if ch["pick"] not in s.get("options", []):
                    raise KitchenError(f"the pick is one of the options: {', '.join(s.get('options', []))}")
                s["pick"] = ch["pick"]
            if "done" in ch:
                if ch["done"]:
                    s["done_at"] = s["done_at"] or _iso(_now()); s["place"] = "leftovers"
                else:
                    s["done_at"] = None; s["place"] = PLACE_BY_KIND[s["kind"]]
            # Every plain line ticked: the sheet is done. A pick is not a tick: deciding is not finishing, so a
            # sheet with choices on it stays where it was once they are picked, for whoever picks the work up,
            # until someone says done. A sheet with no lines is done when you say so.
            plain = [ln for ln in s["lines"] if not ln.get("options")]
            has_choices = len(plain) != len(s["lines"]) or (s.get("kind") == "decision" and s.get("options"))
            if plain and all(ln.get("done") for ln in plain) and not has_choices and not s["done_at"] and "done" not in ch:
                s["done_at"] = _iso(_now()); s["place"] = "leftovers"
            s["updated"] = _iso(_now())
            self._save()
            return self._view(s)

    def take_down(self, sheet_id: str) -> bool:
        """Off the fridge for good. Finished sheets go to the leftovers on their own; this is for
        a sheet that should never have been left."""
        with self._lock:
            gone = self._data["sheets"].pop(sheet_id, None) is not None
            if gone:
                # what was stuck to it comes down with it
                for rid in [r for r, s in self._data["sheets"].items() if s.get("reply_to") == sheet_id]:
                    self._data["sheets"].pop(rid, None)
                self._save()
            return gone

    def __len__(self) -> int:
        return len(self._data["sheets"])
