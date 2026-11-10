"""SerenKitchen's config: dataclasses on the shared Meninges blocks, like Psycheion and Theatre.

Where it's read from, first found wins:

    --config  ->  $SEREN_KITCHEN_CONFIG  ->  ~/seren-kitchen/seren-kitchen.yaml  ->  defaults

The fridges start as the whole family (_constellation.py) and the yaml adds, drops
or recolours. The fonts are PATHS to files on this box, never shipped: the display
faces on the freezer are whatever you own a licence for, and the handwriting on the
notes is whoever's hand lives here. Unset, the page falls back to system fonts.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from seren_meninges import ServerConfig

from ._constellation import default_fridges
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

    @classmethod
    def from_dict(cls, d: Any) -> "HouseConfig":
        d = d if isinstance(d, dict) else {}
        return cls(person=str(d.get("person") or "").strip()[:40], partner=str(d.get("partner") or "").strip()[:40])


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


def _merge_fridges(raw: Any, drop: Any) -> List[Dict[str, Any]]:
    """The family, then the yaml's say: a listed name that exists is recoloured or renamed
    in place, a new one is appended, and `drop` takes names off the wall."""
    fridges = default_fridges()
    by_name = {f["name"]: f for f in fridges}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"])
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
    fridges: List[Dict[str, Any]] = field(default_factory=default_fridges)
    # a decision nobody has picked in this many days goes off like milk
    sour_after_days: float = 7.0
    github: GithubConfig = field(default_factory=GithubConfig)
    house: HouseConfig = field(default_factory=HouseConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)

    @property
    def host(self) -> str:
        return self.server.host

    @property
    def port(self) -> int:
        return self.server.port

    @property
    def state_path(self) -> Path:
        return Path(os.path.expanduser(self.state_dir))


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
    )
