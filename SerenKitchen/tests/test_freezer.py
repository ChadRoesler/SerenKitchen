"""The freezer against a fake GitHub: a release wins, a tag stands in, a run's conclusion becomes the build,
a dead repo keeps its facts and shows its error, and the refresh route runs a pass on demand."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from seren_kitchen._constellation import default_fridges
from seren_kitchen.app import create_app
from seren_kitchen.config import GithubConfig, KitchenConfig
from seren_kitchen.freezer import Freezer
from seren_kitchen.store import Store


class FakeHub:
    def __init__(self):
        self.calls = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request.url.path)
        p = request.url.path
        if "/SerenMemory/releases/latest" in p:
            return httpx.Response(200, json={"tag_name": "v5.6.1", "published_at": "2026-11-08T08:10:39Z"})
        if "/SerenMemory/actions/runs" in p:
            return httpx.Response(200, json={"workflow_runs": [{"status": "completed", "conclusion": "success",
                                                                "updated_at": "2026-11-08T08:10:59Z", "html_url": "https://x/run/1"}]})
        if "/SerenSinew/releases/latest" in p:
            return httpx.Response(404, json={"message": "Not Found"})
        if "/SerenSinew/tags" in p:
            return httpx.Response(200, json=[{"name": "v5.7.0"}])
        if "/SerenSinew/actions/runs" in p:
            return httpx.Response(200, json={"workflow_runs": [{"status": "in_progress", "conclusion": None,
                                                                "updated_at": "2026-11-09T01:00:00Z", "html_url": "https://x/run/2"}]})
        if "/SerenTheatre/releases/latest" in p:
            return httpx.Response(200, json={"tag_name": "v5.2.0", "published_at": "2026-10-01T00:00:00Z"})
        if "/SerenTheatre/actions/runs" in p:
            return httpx.Response(200, json={"workflow_runs": [{"status": "completed", "conclusion": "failure",
                                                                "updated_at": "2026-10-02T00:00:00Z", "html_url": "https://x/run/3"}]})
        if "/SerenLoci/" in p:
            raise httpx.ConnectError("no route to host", request=request)
        return httpx.Response(404, json={"message": "Not Found"})


FRIDGES = [f for f in default_fridges() if f["name"] in ("seren-memory", "seren-sinew", "seren-theatre", "seren-loci")]


@pytest.mark.anyio
async def test_a_pass_reads_releases_tags_and_runs(tmp_path):
    hub = FakeHub()
    st = Store(tmp_path / "k.json", FRIDGES)
    fz = Freezer(st, FRIDGES, transport=httpx.MockTransport(hub))
    res = await fz.run_once()
    mem = st.fridges()[[f["name"] for f in st.fridges()].index("seren-memory")]["facts"]
    assert mem["release"] == "5.6.1" and mem["released_at"] == "2026-11-08" and mem["build"] == "ok" and mem["build_url"] == "https://x/run/1"
    sinew = next(f for f in st.fridges() if f["name"] == "seren-sinew")["facts"]
    assert sinew["release"] == "5.7.0" and "released_at" not in sinew and sinew["build"] == "running"
    theatre = next(f for f in st.fridges() if f["name"] == "seren-theatre")["facts"]
    assert theatre["build"] == "failed"
    loci = next(f for f in st.fridges() if f["name"] == "seren-loci")["facts"]
    assert "ConnectError" in loci["freezer_error"] and "error" in res["seren-loci"]
    assert fz.passes == 1 and fz.last_pass
    # the dead one keeps what it had from before
    st.set_facts("seren-loci", release="5.5.0")
    await fz.run_once()
    assert next(f for f in st.fridges() if f["name"] == "seren-loci")["facts"]["release"] == "5.5.0"


@pytest.mark.anyio
async def test_a_token_rides_as_a_bearer(tmp_path):
    seen = {}

    def hub(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(404, json={})
    fz = Freezer(Store(tmp_path / "k.json", FRIDGES[:1]), FRIDGES[:1], token="gh-secret", transport=httpx.MockTransport(hub))
    await fz.run_once()
    assert seen["auth"] == "Bearer gh-secret"


def test_the_refresh_route_and_the_wall_show_what_the_freezer_read(tmp_path):
    hub = FakeHub()
    cfg = KitchenConfig(server=ServerConfig(host="127.0.0.1", port=7431), state_dir=str(tmp_path / "s"), fridges=FRIDGES,
                        github=GithubConfig(enabled=True, interval_minutes=60))
    with TestClient(create_app(cfg, github_transport=httpx.MockTransport(hub), run_freezer=False)) as c:
        r = c.post("/api/freezer/refresh").json()
        assert r["read"] == 3 and set(r["unreadable"]) == {"seren-loci"} and r["passes"] == 1
        k = c.get("/api/kitchen").json()
        facts = {f["name"]: f["facts"] for f in k["fridges"]}
        assert facts["seren-memory"]["release"] == "5.6.1" and facts["seren-memory"]["build"] == "ok"
        assert facts["seren-sinew"]["build"] == "running"
        assert "freezer_error" in facts["seren-loci"]
        assert "freezer" in c.get("/health").json()["features"]
    assert len([p for p in hub.calls if "SerenMemory" in p]) == 2            # a release and a run: two calls a fridge
