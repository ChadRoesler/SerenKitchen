"""The MCP mount, with the SDK installed: the three transport fixes, the app's lifespan running the session
manager, the bearer over /mcp, and a client speaking the protocol to the tools over HTTP."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("mcp")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from seren_meninges import ServerConfig

from conftest import WALL
from seren_kitchen._describe import PORT
from seren_kitchen.app import create_app
from seren_kitchen.config import HouseConfig, KitchenConfig, McpConfig, load_config
from seren_kitchen.mcp.server import _count_tools, mount_mcp_routes
from seren_kitchen.mcp.tools import TOOL_NAMES, KitchenToolImpl
from seren_kitchen.store import Store


def impl(tmp_path) -> KitchenToolImpl:
    return KitchenToolImpl(Store(tmp_path / "k.json", [{"name": "seren-memory", "display": "Memory"}]), author=lambda: "ada")


def config(tmp_path, bearer: str = "", **kw) -> KitchenConfig:
    return KitchenConfig(fridges=WALL, server=ServerConfig(host="127.0.0.1", port=PORT, bearer_token=bearer), state_dir=str(tmp_path / "state"),
                         house=HouseConfig(person="alex", partner="ada"), **kw)


def paths(app) -> list[str]:
    return [getattr(r, "path", "") for r in app.routes]


class Session:
    """A client speaking MCP's streamable HTTP by hand: enough protocol to list the tools and call one."""

    def __init__(self, c: TestClient, bearer: str = ""):
        self.c, self.n, self.sid = c, 0, ""
        self.headers = {"Accept": "application/json, text/event-stream", **({"Authorization": f"Bearer {bearer}"} if bearer else {})}
        hello = self.ask("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "a test", "version": "0"}})
        self.server = hello["result"]
        self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def post(self, body: dict):
        r = self.c.post("/mcp", json=body, headers={**self.headers, **({"mcp-session-id": self.sid} if self.sid else {})})
        assert r.status_code in (200, 202), f"{r.status_code}: {r.text[:300]}"
        self.sid = r.headers.get("mcp-session-id") or self.sid
        return r

    def ask(self, method: str, params: dict | None = None) -> dict:
        self.n += 1
        r = self.post({"jsonrpc": "2.0", "id": self.n, "method": method, **({"params": params} if params is not None else {})})
        if r.headers.get("content-type", "").startswith("text/event-stream"):
            return json.loads([ln[5:] for ln in r.text.splitlines() if ln.startswith("data:")][-1])
        return r.json()

    def call(self, tool: str, **args) -> dict:
        return self.ask("tools/call", {"name": tool, "arguments": args})["result"]


def test_mount_registers_every_tool_and_applies_the_three_fixes(tmp_path, monkeypatch):
    monkeypatch.delenv("SEREN_KITCHEN_MCP_ALLOWED_HOSTS", raising=False)
    monkeypatch.delenv("SEREN_KITCHEN_MCP_ALLOWED_ORIGINS", raising=False)
    app = FastAPI()
    mcp = mount_mcp_routes(app, impl(tmp_path))
    assert _count_tools(mcp) == len(TOOL_NAMES)
    assert paths(app).count("/mcp") == 2 and app.state.mcp_path == "/mcp"   # the mount, and the bare path beside it
    if hasattr(mcp.settings, "streamable_http_path"):
        assert mcp.settings.streamable_http_path == "/"                    # /mcp, not /mcp/mcp
    assert getattr(mcp, "session_manager", None) is not None                # the lifespan has something to run
    ts = getattr(mcp.settings, "transport_security", None)
    if ts is not None:
        assert ts.enable_dns_rebinding_protection is False                  # off, like the rest of the family


def test_the_path_moves_the_host_check_rearms_and_a_second_mount_replaces_the_first(tmp_path, monkeypatch):
    monkeypatch.setenv("SEREN_KITCHEN_MCP_MOUNT", "kitchen-mcp")
    monkeypatch.setenv("SEREN_KITCHEN_MCP_ALLOWED_HOSTS", "kitchen-box:7431")
    app = FastAPI()
    mcp = mount_mcp_routes(app, impl(tmp_path))
    assert paths(app).count("/kitchen-mcp") == 2 and "/mcp" not in paths(app)
    ts = getattr(mcp.settings, "transport_security", None)
    if ts is not None:
        assert ts.enable_dns_rebinding_protection is True and "kitchen-box:7431" in ts.allowed_hosts
    mount_mcp_routes(app, impl(tmp_path))
    assert paths(app).count("/kitchen-mcp") == 2


def test_the_kitchen_says_where_its_door_is_and_who_it_signs_as(tmp_path):
    with TestClient(create_app(config(tmp_path), run_freezer=False)) as c:
        assert c.get("/health").json()["mcp"] == "/mcp" and c.get("/").json()["mcp"] == "/mcp"
        assert c.get("/api/settings").json()["mcp"] == {"path": "/mcp", "signs_as": "ada"}
        c.post("/api/settings/house", json={"partner": "bea"})               # the page renames the partner
        assert c.get("/api/settings").json()["mcp"]["signs_as"] == "bea"
    with TestClient(create_app(config(tmp_path, mcp=McpConfig(author="cy")), run_freezer=False)) as c:
        assert c.get("/api/settings").json()["mcp"]["signs_as"] == "cy"      # the yaml's name wins
    with TestClient(create_app(config(tmp_path, mcp=McpConfig(enabled=False)), run_freezer=False)) as c:
        assert c.get("/health").json()["mcp"] is None and "/mcp" not in paths(c.app)
        assert c.get("/api/kitchen").status_code == 200                      # and the kitchen is the kitchen without it


def test_the_yaml_block(tmp_path):
    p = tmp_path / "k.yaml"
    p.write_text("mcp:\n  enabled: false\n  author: ' ada '\n", encoding="utf-8")
    cfg = load_config(str(p))
    assert cfg.mcp.enabled is False and cfg.mcp.author == "ada"
    p.write_text("state_dir: x\n", encoding="utf-8")
    assert load_config(str(p)).mcp == McpConfig(enabled=True, author="")


def test_a_client_lists_the_tools_and_uses_the_board(tmp_path):
    with TestClient(create_app(config(tmp_path), run_freezer=False)) as c:
        s = Session(c)
        assert s.server["serverInfo"]["name"] == "seren-kitchen" and "not a task" in s.server["instructions"]
        tools = {t["name"]: t for t in s.ask("tools/list")["result"]["tools"]}
        assert tuple(tools) == TOOL_NAMES
        leave = tools["kitchen_leave"]
        assert "signed as me" in leave["description"] and leave["inputSchema"]["required"] == ["fridge", "title"]
        assert "author" not in leave["inputSchema"]["properties"]
        assert "more than one of me" in leave["inputSchema"]["properties"]["hand"]["description"]
        res = s.call("kitchen_leave", fridge="seren-memory", title="left through the door", lines=["one"])
        assert not res.get("isError"), res
        left = json.loads(res["content"][0]["text"])
        assert left["signed"] == "ada"
        # the page and the door are one board
        assert c.get(f"/api/sheets/{left['sheet']}").json()["author"] == "ada"
        c.post(f"/api/sheets/{left['sheet']}/reply", json={"body": "seen", "author": "alex"})
        seen = json.loads(s.call("kitchen_sheet", sheet=left["sheet"])["content"][0]["text"])
        assert [r["by"] for r in seen["stuck_on_it"]] == ["alex"]
        wall = json.loads(s.call("kitchen_wall")["content"][0]["text"])
        assert wall["signed_as"] == "ada" and wall["house"]["person"] == "alex"
        # a refusal is the tool's error, with the store's own words in it
        bad = s.call("kitchen_leave", fridge="seren-nope", title="x")
        assert bad["isError"] and "no fridge called 'seren-nope'" in bad["content"][0]["text"]


def test_the_door_wants_the_bearer_when_the_kitchen_has_one(tmp_path):
    with TestClient(create_app(config(tmp_path, bearer="s3cret"), run_freezer=False)) as c:
        hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "a test", "version": "0"}}}
        accept = {"Accept": "application/json, text/event-stream"}
        assert c.post("/mcp", json=hello, headers=accept).status_code == 401
        assert c.post("/mcp", json=hello, headers={**accept, "Authorization": "Bearer wrong"}).status_code == 401
        s = Session(c, bearer="s3cret")
        assert len(s.ask("tools/list")["result"]["tools"]) == len(TOOL_NAMES)


def test_the_lifespan_can_run_twice(tmp_path):
    app = create_app(config(tmp_path), run_freezer=False)
    for title in ("first", "second"):
        with TestClient(app) as c:
            assert not Session(c).call("kitchen_leave", fridge="seren-memory", title=title).get("isError")
            assert paths(c.app).count("/mcp") == 2


def test_the_address_answers_in_place_with_or_without_the_slash(tmp_path):
    """/mcp is the address every doc gives. A redirect to /mcp/ works for a client that follows one and is a
    dead door for one that does not."""
    hello = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "a test", "version": "0"}}}
    with TestClient(create_app(config(tmp_path), run_freezer=False), follow_redirects=False) as c:
        for address in ("/mcp", "/mcp/"):
            r = c.post(address, json=hello, headers={"Accept": "application/json, text/event-stream"})
            assert r.status_code == 200 and r.headers.get("mcp-session-id"), f"{address}: {r.status_code} {r.text[:200]}"
