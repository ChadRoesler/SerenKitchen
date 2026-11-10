"""The freezer: what is live for each fridge, read from GitHub.

For every fridge with a repo, the latest release (or the newest tag when a repo
cuts none) and the latest workflow run's conclusion become the fridge's facts:
`release`, `released_at`, `build` (ok, failed, running, none), `build_at`,
`build_url`. So what is live is visible on the wall without asking anything else.

Unauthenticated GitHub allows 60 calls an hour and a wall of nineteen fridges
costs 38 a pass, so the default is one pass an hour; a token (github.token_env)
raises the ceiling to 5000 and the pass can run every few minutes. A pass never
raises: a repo that cannot be read keeps its last facts and the error is kept
on the fridge as `freezer_error`, so a dead wire shows as a dead wire.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any, Optional

import httpx

from ._diag import diag
from .store import Store

API = "https://api.github.com"


class RateLimited(httpx.HTTPError):
    """GitHub said no more this hour. An HTTPError so every catch below already handles it."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message

    def __str__(self) -> str:
        return self.message


class Freezer:
    def __init__(self, store: Store, fridges: list[dict[str, Any]], *, interval_minutes: float = 60.0,
                 token: str = "", transport: Optional[httpx.AsyncBaseTransport] = None, api: str = API,
                 token_source: Optional[Any] = None):
        self.store = store
        self.repos = {f["name"]: f.get("repo") for f in fridges if f.get("repo")}
        self.interval = max(1.0, float(interval_minutes)) * 60.0
        self._token = token
        self.token_source = token_source          # a callable asked on every pass: the settings file, then the env
        self.transport = transport
        self.api = api.rstrip("/")
        self.passes = 0
        self.last_pass: Optional[str] = None

    @property
    def token(self) -> str:
        if self.token_source is not None:
            try:
                t = self.token_source()
                if t:
                    return t
            except Exception:  # noqa: BLE001 - a broken source means no token, not a dead freezer
                pass
        return self._token

    def set_fridges(self, fridges: list[dict[str, Any]]) -> None:
        self.repos = {f["name"]: f.get("repo") for f in fridges if f.get("repo")}

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "User-Agent": "seren-kitchen"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    async def _get(self, client: httpx.AsyncClient, path: str) -> Any:
        r = await client.get(f"{self.api}{path}", headers=self._headers(), timeout=15.0)
        if r.status_code == 404:
            return None
        if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
            # the hourly budget is spent: say when it comes back, and whether a token would help
            import time
            try:
                back = time.strftime("%H:%M", time.localtime(int(r.headers.get("X-RateLimit-Reset", "0"))))
            except (ValueError, OSError):
                back = "the top of the hour"
            raise RateLimited(f"GitHub's hourly budget is spent; it comes back at {back}"
                              + ("" if self.token else " (a token in github.token_env lifts it from 60 calls to 5000)"))
        r.raise_for_status()
        return r.json()

    async def read(self, client: httpx.AsyncClient, repo: str) -> dict[str, Any]:
        """One repo's facts. A release wins; a tag stands in when there are none."""
        facts: dict[str, Any] = {}
        rel = await self._get(client, f"/repos/{repo}/releases/latest")
        if rel and rel.get("tag_name"):
            facts["release"] = str(rel["tag_name"]).lstrip("v")
            facts["released_at"] = (rel.get("published_at") or "")[:10]
        else:
            tags = await self._get(client, f"/repos/{repo}/tags?per_page=1")
            if tags:
                facts["release"] = str(tags[0].get("name", "")).lstrip("v")
        runs = await self._get(client, f"/repos/{repo}/actions/runs?per_page=1")
        run = ((runs or {}).get("workflow_runs") or [None])[0]
        if run:
            if run.get("status") != "completed":
                facts["build"] = "running"
            else:
                facts["build"] = "ok" if run.get("conclusion") == "success" else "failed"
            facts["build_at"] = (run.get("updated_at") or "")[:10]
            facts["build_url"] = run.get("html_url") or ""
        else:
            facts["build"] = "none"
        return facts

    async def refresh_one(self, name: str) -> dict[str, Any]:
        """One fridge, now: the dispenser button. Facts set, or the error kept on the fridge."""
        repo = self.repos.get(name)
        if not repo:
            return {"error": "this fridge has no repo to read"}
        async with httpx.AsyncClient(transport=self.transport) as client:
            try:
                facts = await self.read(client, repo)
                facts["freezer_error"] = None
                return self.store.set_facts(name, **facts)
            except RateLimited as exc:
                self.store.set_facts(name, freezer_error=str(exc))
                return {"error": str(exc)}
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                why = f"{type(exc).__name__}: {str(exc)[:120]}"
                self.store.set_facts(name, freezer_error=why)
                return {"error": why}

    async def run_once(self) -> dict[str, Any]:
        """One pass over every fridge with a repo. Returns {fridge: facts | {"error": ...}}."""
        out: dict[str, Any] = {}
        async with httpx.AsyncClient(transport=self.transport) as client:
            for name, repo in self.repos.items():
                try:
                    facts = await self.read(client, repo)
                    facts["freezer_error"] = None
                    self.store.set_facts(name, **facts)
                    out[name] = facts
                except RateLimited as exc:
                    # no point asking the other fridges this hour: mark them all and stop the pass
                    for rest in list(self.repos)[list(self.repos).index(name):]:
                        self.store.set_facts(rest, freezer_error=str(exc))
                        out[rest] = {"error": str(exc)}
                    break
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    why = f"{type(exc).__name__}: {str(exc)[:120]}"
                    self.store.set_facts(name, freezer_error=why)
                    out[name] = {"error": why}
        self.passes += 1
        import time
        self.last_pass = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())
        return out

    def fresh_enough(self) -> bool:
        """True when every fridge with a repo was read within the interval: a restart then waits
        instead of spending another pass (a few restarts in an hour can spend the whole
        unauthenticated budget)."""
        import time
        for name in self.repos:
            f = next((x for x in self.store.fridges() if x["name"] == name), None)
            at = (f or {}).get("facts", {}).get("checked_at")
            if not at:
                return False
            try:
                t = time.mktime(time.strptime(at, "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                return False
            if time.time() - t > self.interval:
                return False
        return True

    async def run(self) -> None:
        """Forever: a pass, then sleep the interval. Cancelled with the app. A kitchen restarted
        with fresh facts sleeps first."""
        if self.fresh_enough():
            diag("[seren-kitchen] freezer: the facts are fresh; the first pass waits an interval")
            await asyncio.sleep(self.interval)
        while True:
            try:
                res = await self.run_once()
                bad = [n for n, f in res.items() if "error" in f]
                diag(f"[seren-kitchen] freezer: {len(res) - len(bad)} fridges read from GitHub"
                     + (f", {len(bad)} unreadable ({', '.join(bad[:3])}{'...' if len(bad) > 3 else ''})" if bad else ""))
            except Exception as exc:  # noqa: BLE001 - the loop outlives any one bad pass
                diag(f"[seren-kitchen] freezer pass failed: {exc}")
            await asyncio.sleep(self.interval)


def token_from_env(name: str) -> str:
    return os.environ.get(name, "") if name else ""
