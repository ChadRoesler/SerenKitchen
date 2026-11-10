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
from pathlib import Path
from typing import Any, Optional

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
                                     "sour_after_days": None}
        self._load()

    # ── the file ──────────────────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(self.data.get(k), dict) and isinstance(v, dict):
                    self.data[k].update(v)
                else:
                    self.data[k] = v
            self.data["fonts"].setdefault("hands", {})
            self.data["fridges"].setdefault("order", []); self.data["fridges"].setdefault("extra", [])
            self.data["fridges"].setdefault("hidden", []); self.data["fridges"].setdefault("overrides", {})

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
                "sour_after_days": self.data.get("sour_after_days")}
