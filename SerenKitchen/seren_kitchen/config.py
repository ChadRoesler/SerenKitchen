"""SerenKitchen's config: dataclasses on the shared Meninges blocks, like Psycheion and Theatre.

Where it's read from, first found wins:

    --config  ->  $SEREN_KITCHEN_CONFIG  ->  ~/seren-kitchen/seren-kitchen.yaml  ->  defaults

The wall starts with one fridge, the house's own (the big fridge), and the fridges
are whatever the yaml lists and the page adds: a kitchen ships knowing no repos. The fonts are PATHS to files on this box, never shipped: the display
faces on the freezer are whatever you own a licence for, and the handwriting on the
notes is whoever's hand lives here. Unset, the page falls back to system fonts.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from seren_meninges import ServerConfig

from ._describe import PORT as DEFAULT_PORT
from ._diag import diag

try:
    import yaml
    _HAS_YAML = True
except ImportError:  # pragma: no cover - pyyaml is a dependency
    _HAS_YAML = False

# Loopback unless the yaml says otherwise: a kitchen holds notes between people,
# and widening it is something you do on purpose, with a token.
DEFAULT_HOST = "127.0.0.1"
DEFAULT_STATE_DIR = "~/seren-kitchen/state"


@dataclass
class FontsConfig:
    """Paths to font files on this box, served at /api/fonts/<slot>. Blank: the page's fallbacks.
    `hands` is one hand per author: a note signed by that name is drawn in that font; anyone
    else gets `hand`."""
    name: str = ""       # the repo name on the freezer (a display face)
    freezer: str = ""    # the facts on the freezer (fridge-magnet letters, say)
    hand: str = ""       # the handwriting on the notes
    hands: Dict[str, str] = field(default_factory=dict)   # author -> path

    @classmethod
    def from_dict(cls, d: Any) -> "FontsConfig":
        d = d if isinstance(d, dict) else {}
        hands = d.get("hands") if isinstance(d.get("hands"), dict) else {}
        return cls(name=str(d.get("name") or ""), freezer=str(d.get("freezer") or ""), hand=str(d.get("hand") or ""),
                   hands={str(k).strip().lower(): str(v) for k, v in hands.items() if v})

    def path(self, slot: str) -> Optional[Path]:
        raw = getattr(self, slot, "") if slot in ("name", "freezer", "hand") else ""
        return Path(os.path.expanduser(raw)) if raw else None

    def hand_for(self, author: str) -> Optional[Path]:
        raw = self.hands.get((author or "").strip().lower())
        return Path(os.path.expanduser(raw)) if raw else None


@dataclass
class HouseConfig:
    """Whose house this is: the names the page puts on 'to the person' and 'to the partner'.
    Blank, it says 'the person' and 'the partner'."""
    person: str = ""
    partner: str = ""
    # the slug of the house's own fridge: the big fridge the wall is drawn on, always there
    fridge: str = "house"

    @classmethod
    def from_dict(cls, d: Any) -> "HouseConfig":
        d = d if isinstance(d, dict) else {}
        fridge = str(d.get("fridge") or "").strip().lower()[:40]
        if fridge and not _SLUG.fullmatch(fridge):
            diag(f"[seren-kitchen] config: house.fridge {fridge!r} is not a slug; keeping 'house'")
            fridge = ""
        return cls(person=str(d.get("person") or "").strip()[:40], partner=str(d.get("partner") or "").strip()[:40],
                   fridge=fridge or "house")


@dataclass
class GithubConfig:
    """The freezer's source: releases and workflow runs read from GitHub for every fridge with a repo.
    Unauthenticated GitHub allows 60 calls an hour and a pass costs two per fridge, so the default
    interval is an hour; a token (the NAME of an env var holding it) lifts the ceiling to 5000."""
    enabled: bool = True
    interval_minutes: float = 60.0
    token_env: str = ""

    @classmethod
    def from_dict(cls, d: Any) -> "GithubConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        out.enabled = bool(d.get("enabled", out.enabled))
        try:
            out.interval_minutes = float(d.get("interval_minutes", out.interval_minutes))
        except (TypeError, ValueError):
            pass
        out.token_env = str(d.get("token_env") or "")
        return out


@dataclass
class UpdatesConfig:
    """"Is there a newer seren-kitchen" checking. Cosmetic, opt-outable."""
    enabled: bool = True
    check_interval_hours: float = 6.0
    index_url: str = "https://pypi.org/pypi/{distribution}/json"
    allow_prerelease: bool = False

    @classmethod
    def from_dict(cls, d: Any) -> "UpdatesConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        out.enabled = bool(d.get("enabled", out.enabled))
        try:
            out.check_interval_hours = float(d.get("check_interval_hours", out.check_interval_hours))
        except (TypeError, ValueError):
            pass
        out.index_url = str(d.get("index_url") or out.index_url)
        out.allow_prerelease = bool(d.get("allow_prerelease", out.allow_prerelease))
        return out


@dataclass
class MagnetsConfig:
    """A magnet's life, as an installer's defaults: the house page's own say beats these. Bright while its session
    was seen within grey_after_hours, grey after, in the drawer under the counter once quiet past drawer_after_days.
    stick_on_start: a session in a folder that is a fridge's repo holds it from its first minute.
    trim_prefix: a prefix every fridge name of the house shares, left off the hand a session takes from its repo
    (fridge acme-billing, prefix acme-: the hand is billing). Blank: the hand is the fridge's whole name."""
    grey_after_hours: float = 12.0
    drawer_after_days: float = 3.0
    stick_on_start: bool = True
    trim_prefix: str = ""

    @classmethod
    def from_dict(cls, d: Any) -> "MagnetsConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        for key, floor in (("grey_after_hours", 0.25), ("drawer_after_days", 0.5)):
            try:
                if key in d:
                    setattr(out, key, max(floor, float(d[key])))
            except (TypeError, ValueError):
                diag(f"[seren-kitchen] config: magnets.{key} is a number; keeping {getattr(out, key)}")
        if "stick_on_start" in d:
            out.stick_on_start = bool(d["stick_on_start"])
        out.trim_prefix = str(d.get("trim_prefix") or "").strip().lower()[:20]
        return out


@dataclass
class BackupConfig:
    """Snapshots of the kitchen (seren_sinew.stores), on the kitchen's own schedule, like every other
    store in the family: kitchen.json whole, the settings, the art, the magnets' faces and the fonts.
    The GitHub token is never in one. `dir` blank is `backups` beside the state folder, not inside it,
    so a `cp -r` of the state does not carry every snapshot along with it.

    allow_pull: whether a snapshot may be handed over HTTP (how a Lodestar stashes it on another box).
    On by default: the kitchen is the house's shared surface, not a diary.
    restore_from + restore_reason: put a snapshot back at startup, into an EMPTY kitchen only. No route
    does it; it is these two keys and a restart."""
    enabled: bool = True
    dir: str = ""
    every_hours: float = 24.0          # 0 = never on its own
    keep_daily: int = 14
    keep_weekly: int = 8
    allow_pull: bool = True
    compress: str = "gz"
    restore_from: str = ""
    restore_reason: str = ""

    @classmethod
    def from_dict(cls, d: Any) -> "BackupConfig":
        d = d if isinstance(d, dict) else {}
        out = cls()
        for key in ("enabled", "allow_pull"):
            if key in d:
                setattr(out, key, bool(d[key]))
        for key, kind in (("every_hours", float), ("keep_daily", int), ("keep_weekly", int)):
            try:
                if key in d:
                    setattr(out, key, kind(d[key]))
            except (TypeError, ValueError):
                diag(f"[seren-kitchen] config: backup.{key} is a number; keeping {getattr(out, key)}")
        for key in ("dir", "restore_from", "restore_reason"):
            setattr(out, key, str(d.get(key) or ""))
        c = str(d.get("compress") or out.compress)
        out.compress = c if c in ("gz", "xz", "none") else "gz"
        return out


@dataclass
class McpConfig:
    """The kitchen's own MCP endpoint (/mcp), for a partner in a house with no Workbench. Mounted when the
    [mcp] extra is installed and this is on. `author` is the one name everything left through it is signed
    with; blank, it is what the house calls its partner. No tool takes an author, so a tool call cannot sign
    as the person of the house."""
    enabled: bool = True
    author: str = ""

    @classmethod
    def from_dict(cls, d: Any) -> "McpConfig":
        d = d if isinstance(d, dict) else {}
        return cls(enabled=bool(d.get("enabled", True)), author=str(d.get("author") or "").strip()[:40])


_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def house_fridge(name: str = "house") -> Dict[str, Any]:
    """The house's own fridge as the wall carries it, when nothing says otherwise."""
    return {"name": name, "display": "The House", "group": "house", "accent": "#c9c2d6", "repo": ""}


def _merge_fridges(raw: Any, drop: Any) -> List[Dict[str, Any]]:
    """The yaml's fridges, in its order: a name listed twice is the first one changed by the second, and `drop`
    takes names off the wall. Nothing is on it that the yaml (or later the page) did not put there; the house's
    own fridge is added by the app whatever this says."""
    fridges: List[Dict[str, Any]] = []
    by_name: Dict[str, Dict[str, Any]] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"]).strip()
        if not _SLUG.fullmatch(name):
            diag(f"[seren-kitchen] config: fridge {name!r} is not a slug (lowercase letters, digits, dashes); left off")
            continue
        target = by_name.get(name)
        if target is None:
            target = {"name": name, "display": name, "group": "other", "accent": "#cccccc", "repo": ""}
            fridges.append(target); by_name[name] = target
        for key in ("display", "group", "accent", "repo"):
            if item.get(key) is not None:
                target[key] = str(item[key])
    gone = {str(n) for n in (drop if isinstance(drop, list) else [])}
    return [f for f in fridges if f["name"] not in gone]


@dataclass
class KitchenConfig:
    server: ServerConfig = field(default_factory=lambda: ServerConfig(host=DEFAULT_HOST, port=DEFAULT_PORT))
    state_dir: str = DEFAULT_STATE_DIR
    fonts: FontsConfig = field(default_factory=FontsConfig)
    fridges: List[Dict[str, Any]] = field(default_factory=list)
    # a decision nobody has picked in this many days goes off like milk
    sour_after_days: float = 7.0
    github: GithubConfig = field(default_factory=GithubConfig)
    house: HouseConfig = field(default_factory=HouseConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)
    magnets: MagnetsConfig = field(default_factory=MagnetsConfig)
    mcp: McpConfig = field(default_factory=McpConfig)

    @property
    def host(self) -> str:
        return self.server.host

    @property
    def port(self) -> int:
        return self.server.port

    @property
    def state_path(self) -> Path:
        return Path(os.path.expanduser(self.state_dir))

    @property
    def backup_path(self) -> Path:
        """Where snapshots go: the yaml's backup.dir, else `backups` beside the state folder."""
        if self.backup.dir.strip():
            return Path(os.path.expanduser(self.backup.dir))
        return self.state_path.parent / "backups"


def _candidate_paths(explicit: Optional[str]) -> List[Path]:
    out: List[Path] = []
    if explicit:
        out.append(Path(explicit))
    env = os.environ.get("SEREN_KITCHEN_CONFIG")
    if env:
        out.append(Path(env))
    out.append(Path.home() / "seren-kitchen" / "seren-kitchen.yaml")
    return out


def _read_yaml(path: Optional[str]) -> Dict[str, Any]:
    for candidate in _candidate_paths(path):
        if not candidate.is_file():
            continue
        if not _HAS_YAML:
            diag(f"[seren-kitchen] pyyaml missing; ignoring {candidate}")
            return {}
        try:
            loaded = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError("top level of the config is not a mapping")
            diag(f"[seren-kitchen] config: {candidate}")
            return loaded
        except Exception as exc:  # noqa: BLE001 - lenient for a malformed file, and it says so
            diag(f"[seren-kitchen] {candidate} is malformed ({exc}); falling back to defaults")
            return {}
    return {}


def load_config(path: Optional[str] = None) -> KitchenConfig:
    data = _read_yaml(path)
    raw = data.get("server")
    try:
        sour = float(data.get("sour_after_days", 7.0))
    except (TypeError, ValueError):
        sour = 7.0
    return KitchenConfig(
        server=ServerConfig.from_dict(raw if isinstance(raw, dict) else {}, default_port=DEFAULT_PORT,
                                      default_host=DEFAULT_HOST),
        state_dir=str(data.get("state_dir") or DEFAULT_STATE_DIR),
        fonts=FontsConfig.from_dict(data.get("fonts")),
        fridges=_merge_fridges(data.get("fridges"), data.get("drop")),
        sour_after_days=sour,
        github=GithubConfig.from_dict(data.get("github")),
        house=HouseConfig.from_dict(data.get("house")),
        updates=UpdatesConfig.from_dict(data.get("updates")),
        backup=BackupConfig.from_dict(data.get("backup")),
        magnets=MagnetsConfig.from_dict(data.get("magnets")),
        mcp=McpConfig.from_dict(data.get("mcp")),
    )
