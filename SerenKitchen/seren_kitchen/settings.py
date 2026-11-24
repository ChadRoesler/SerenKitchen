"""Settings a person changes from the page, kept in the state folder, on top of the yaml.

The yaml is what an installer can know: where to listen, where the state lives.
Everything a house decides after moving in lives here instead: the fonts (files
uploaded from the page, kept in <state>/fonts), the GitHub token (a file in the
state folder, 600, written once from the page and never shown again), the
fridges (added, recoloured, hidden, reordered), the house's names, how long milk
keeps. So a kitchen on a box nobody wants to ssh into needs no yaml edit for any of it, and nothing
secret is ever in a yaml.

Precedence: a setting here beats the yaml; blank here means "whatever the yaml
says". The effective values are computed by `effective_*` so the app reads one
place.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ._diag import diag

FONT_SLOTS = ("name", "freezer", "hand")
FONT_EXT = {"font/ttf": "ttf", "font/otf": "otf", "font/woff": "woff", "font/woff2": "woff2",
            "application/x-font-ttf": "ttf", "application/octet-stream": "ttf"}
MAX_FONT = 6 * 1024 * 1024
AUTHOR = re.compile(r"[a-z0-9][a-z0-9 _.-]{0,39}")
COLOUR = re.compile(r"#[0-9a-fA-F]{6}")
SLUG = re.compile(r"[a-z][a-z0-9-]{1,40}")


class Settings:
    def __init__(self, state_dir: Path):
        self.state = Path(state_dir)
        self.path = self.state / "settings.json"
        self._lock = threading.Lock()
        self.data: dict[str, Any] = {"fonts": {"hands": {}}, "github": {}, "house": {}, "fridges": {"order": [], "extra": [], "hidden": [], "overrides": {}},
                                     "sour_after_days": None, "magnets": {}}
        self._load()

    # ── the file ──────────────────────────────────────────────────────────────
    def _load(self) -> None:
        """The file, read leniently. It is the page's own notebook, but it is a file on a box and a person can open
        it: a part of it in the wrong shape (a list where the fridges' settings go, say) is left out with a line in
        the log, never a kitchen that will not start. And since the next change from the page writes the file
        whole, what was refused is copied aside first, so nothing a person typed is lost."""
        self.problems: list[str] = []
        try:
            text = self.path.read_text(encoding="utf-8")
        except (FileNotFoundError, OSError):
            return
        try:
            raw = json.loads(text)
        except ValueError as exc:
            self._refused(f"settings.json is not JSON ({exc}); the page's settings start over")
            return
        if not isinstance(raw, dict):
            self._refused(f"settings.json holds a {type(raw).__name__}, not the page's settings; they start over")
            return
        for k, v in raw.items():
            have = self.data.get(k)
            if isinstance(have, dict) and not isinstance(v, dict):
                self.problems.append(f"{k!r} is a {type(v).__name__}, not a mapping")
            elif isinstance(have, dict):
                have.update(v)
            else:
                self.data[k] = v
        shapes = {("fonts", "hands"): dict, ("fridges", "order"): list, ("fridges", "extra"): list,
                  ("fridges", "hidden"): list, ("fridges", "overrides"): dict}
        for (section, key), kind in shapes.items():
            v = self.data[section].get(key)
            if v is not None and not isinstance(v, kind):
                self.problems.append(f"{section}.{key} is a {type(v).__name__}, not a {kind.__name__}")
                v = None
            if v is None:
                self.data[section][key] = kind()
        # a fridge added from the page is a mapping with a name; anything else in the list is left out
        extra = self.data["fridges"]["extra"]
        good = [x for x in extra if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip()]
        if len(good) != len(extra):
            self.problems.append(f"{len(extra) - len(good)} of fridges.extra are not a fridge (a mapping with a name)")
            self.data["fridges"]["extra"] = good
        if self.problems:
            self._refused("settings.json: " + "; ".join(self.problems) + " (left out; the rest is read)", aside=text)

    def _refused(self, why: str, aside: Optional[str] = None) -> None:
        """Say what was refused, keep the file as it was beside it, and carry on."""
        if why not in self.problems:
            self.problems.append(why)
        keep = self.path.with_name(f"settings.json.refused-{time.strftime('%Y%m%d-%H%M%S')}")
        try:
            keep.write_text(aside if aside is not None else self.path.read_text(encoding="utf-8"), encoding="utf-8")
            diag(f"[seren-kitchen] {why}. The file as it was is kept as {keep.name}.")
        except OSError as exc:
            diag(f"[seren-kitchen] {why}. (Could not keep a copy: {exc}.)")

    def _save(self) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # ── fonts: files in <state>/fonts ─────────────────────────────────────────
    def font_dir(self) -> Path:
        return self.state / "fonts"

    def put_font(self, slot: str, data: bytes, ctype: str, author: Optional[str] = None) -> str:
        """Keep an uploaded font for a slot (name, freezer, hand) or an author's hand. Returns the file name."""
        ext = FONT_EXT.get((ctype or "").split(";")[0].strip().lower())
        if not ext or not data or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"wOFF", b"wOF2"):
            raise ValueError("a font is a TTF, OTF, WOFF or WOFF2 file")
        if len(data) > MAX_FONT:
            raise ValueError(f"that font is {len(data) // 1024} KB; the fridge takes up to {MAX_FONT // (1024 * 1024)} MB")
        folder = self.font_dir()
        folder.mkdir(parents=True, exist_ok=True)
        if author is not None:
            a = author.strip().lower()
            if not AUTHOR.fullmatch(a):
                raise ValueError("an author's name is letters, digits, spaces, dots, dashes; up to forty")
            name = f"hand-{re.sub(r'[^a-z0-9]', '_', a)}.{ext}"
        else:
            if slot not in FONT_SLOTS:
                raise ValueError(f"a font slot is one of {', '.join(FONT_SLOTS)}")
            name = f"{slot}.{ext}"
        for old in folder.glob(name.rsplit(".", 1)[0] + ".*"):
            try:
                old.unlink()
            except OSError:
                pass
        (folder / name).write_bytes(data)
        with self._lock:
            if author is not None:
                self.data["fonts"]["hands"][a] = name
            else:
                self.data["fonts"][slot] = name
            self._save()
        return name

    def drop_font(self, slot: Optional[str] = None, author: Optional[str] = None) -> bool:
        with self._lock:
            if author is not None:
                name = self.data["fonts"]["hands"].pop(author.strip().lower(), None)
            else:
                name = self.data["fonts"].pop(slot or "", None)
            if not name:
                return False
            try:
                (self.font_dir() / name).unlink()
            except OSError:
                pass
            self._save()
            return True

    def font_file(self, slot: str) -> Optional[Path]:
        name = self.data["fonts"].get(slot)
        p = self.font_dir() / name if name else None
        return p if p and p.is_file() else None

    def hand_file(self, author: str) -> Optional[Path]:
        name = self.data["fonts"]["hands"].get((author or "").strip().lower())
        p = self.font_dir() / name if name else None
        return p if p and p.is_file() else None

    def hands(self) -> list[str]:
        return sorted(a for a in self.data["fonts"]["hands"] if self.hand_file(a))

    # ── the GitHub token: a file, 600, never read back out ────────────────────
    def token_path(self) -> Path:
        return self.state / "github_token"

    def set_token(self, token: str) -> None:
        token = (token or "").strip()
        if not token:
            try:
                self.token_path().unlink()
            except OSError:
                pass
            return
        if not re.fullmatch(r"[A-Za-z0-9_]{20,255}", token):
            raise ValueError("that does not look like a GitHub token (letters, digits and underscores, 20 or more)")
        self.state.mkdir(parents=True, exist_ok=True)
        p = self.token_path()
        p.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def token(self) -> str:
        try:
            return self.token_path().read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def token_set(self) -> bool:
        return bool(self.token())

    # ── plain values ─────────────────────────────────────────────────────────
    def set_github(self, interval_minutes: Optional[float] = None, enabled: Optional[bool] = None) -> dict[str, Any]:
        with self._lock:
            if interval_minutes is not None:
                self.data["github"]["interval_minutes"] = max(1.0, float(interval_minutes))
            if enabled is not None:
                self.data["github"]["enabled"] = bool(enabled)
            self._save()
            return dict(self.data["github"])

    def set_house(self, person: Optional[str] = None, partner: Optional[str] = None, notes_at: Optional[str] = None,
                  hinge: Optional[str] = None) -> dict[str, Any]:
        with self._lock:
            if person is not None:
                self.data["house"]["person"] = str(person).strip()[:40]
            if partner is not None:
                self.data["house"]["partner"] = str(partner).strip()[:40]
            if notes_at is not None:
                if notes_at not in ("top", "bottom"):
                    raise ValueError("the house's notes go at the top or the bottom")
                self.data["house"]["notes_at"] = notes_at
            if hinge is not None:
                if hinge not in ("left", "right"):
                    raise ValueError("the hinge is left or right")
                self.data["house"]["hinge"] = hinge
            self._save()
            return dict(self.data["house"])

    def set_magnets(self, grey_after_hours: Optional[float] = None, drawer_after_days: Optional[float] = None,
                    stick_on_start: Optional[bool] = None) -> dict[str, Any]:
        """How long a magnet stays bright, how long until it goes in the drawer under the counter, and whether a
        session in a fridge's repo holds it from its first minute."""
        with self._lock:
            cur = self.data.setdefault("magnets", {})
            if grey_after_hours is not None:
                cur["grey_after_hours"] = max(0.25, float(grey_after_hours))
            if drawer_after_days is not None:
                cur["drawer_after_days"] = max(0.5, float(drawer_after_days))
            if stick_on_start is not None:
                cur["stick_on_start"] = bool(stick_on_start)
            self._save()
            return dict(cur)

    def set_sour(self, days: float) -> float:
        with self._lock:
            self.data["sour_after_days"] = max(0.0, float(days))
            self._save()
            return self.data["sour_after_days"]

    # ── fridges: added, changed, hidden, ordered ─────────────────────────────
    def add_fridge(self, name: str, display: str = "", group: str = "other", accent: str = "#cccccc", repo: str = "") -> dict[str, Any]:
        name = (name or "").strip().lower()
        if not SLUG.fullmatch(name):
            raise ValueError("a fridge's name is a slug: letters, digits and dashes, like my-side-project")
        if not COLOUR.fullmatch(accent or ""):
            raise ValueError("a colour is #rrggbb")
        f = {"name": name, "display": (display or name).strip()[:40], "group": (group or "other").strip()[:20], "accent": accent, "repo": (repo or "").strip()[:120]}
        with self._lock:
            extra = [x for x in self.data["fridges"]["extra"] if x.get("name") != name]
            extra.append(f); self.data["fridges"]["extra"] = extra
            self._save()
        return f

    def change_fridge(self, name: str, **ch: Any) -> dict[str, Any]:
        ov: dict[str, Any] = {}
        for key in ("display", "group", "repo"):
            if ch.get(key) is not None:
                ov[key] = str(ch[key]).strip()[:120]
        if ch.get("accent") is not None:
            if not COLOUR.fullmatch(str(ch["accent"])):
                raise ValueError("a colour is #rrggbb")
            ov["accent"] = str(ch["accent"])
        with self._lock:
            cur = dict(self.data["fridges"]["overrides"].get(name) or {})
            cur.update(ov)
            self.data["fridges"]["overrides"][name] = cur
            if "hidden" in ch:
                hidden = [h for h in self.data["fridges"]["hidden"] if h != name]
                if ch["hidden"]:
                    hidden.append(name)
                self.data["fridges"]["hidden"] = hidden
            self._save()
            return cur

    def added_here(self, name: str) -> bool:
        return any(x.get("name") == name for x in self.data["fridges"]["extra"])

    def drop_fridge(self, name: str) -> bool:
        """A fridge added from the page, gone for good: out of the added ones, and its colour, name, hiding and
        place in the order with it, so one added again by that name starts fresh. False when the page did not add
        it (a yaml's fridge is the yaml's to take away). Its sheets are the store's business, not this file's."""
        with self._lock:
            if not self.added_here(name):
                return False
            f = self.data["fridges"]
            f["extra"] = [x for x in f["extra"] if x.get("name") != name]
            f["overrides"].pop(name, None)
            f["hidden"] = [h for h in f["hidden"] if h != name]
            f["order"] = [n for n in f["order"] if n != name]
            self._save()
            return True

    def set_order(self, names: list[str]) -> list[str]:
        with self._lock:
            self.data["fridges"]["order"] = [str(n) for n in names]
            self._save()
            return list(self.data["fridges"]["order"])

    def effective_fridges(self, base: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """The yaml's fridges, plus the ones added here, with overrides applied, hidden ones gone, in order."""
        out = [dict(f) for f in base]
        have = {f["name"] for f in out}
        for x in self.data["fridges"]["extra"]:
            if x.get("name") and x["name"] not in have:
                out.append(dict(x)); have.add(x["name"])
        for f in out:
            f.update({k: v for k, v in (self.data["fridges"]["overrides"].get(f["name"]) or {}).items() if v not in (None, "")})
        hidden = set(self.data["fridges"]["hidden"])
        out = [f for f in out if f["name"] not in hidden]
        order = {n: i for i, n in enumerate(self.data["fridges"]["order"])}
        out.sort(key=lambda f: (order.get(f["name"], 10_000), 0))
        return out

    def view(self) -> dict[str, Any]:
        """What the page shows: everything but the token itself."""
        return {"fonts": {**{s: self.data["fonts"].get(s) for s in FONT_SLOTS}, "hands": dict(self.data["fonts"]["hands"])},
                "github": {**self.data["github"], "token_set": self.token_set()},
                "house": dict(self.data["house"]), "fridges": {k: (list(v) if isinstance(v, list) else dict(v)) for k, v in self.data["fridges"].items()},
                "sour_after_days": self.data.get("sour_after_days"), "magnets": dict(self.data.get("magnets") or {}),
                **({"refused": list(self.problems)} if self.problems else {})}
