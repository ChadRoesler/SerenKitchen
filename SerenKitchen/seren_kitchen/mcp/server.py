"""Wires a FastMCP server INTO the kitchen's FastAPI app, at /mcp.

Same process, same port, same bearer: the app's auth middleware wraps the mount
like every other route, so a kitchen with a token wants it on /mcp too. The tools
call the Store directly. Mounted at /mcp; SEREN_KITCHEN_MCP_MOUNT moves it.

A near-exact sibling of the family's other in-process mounts (Memory, Loci,
Margin): the same three transport footguns bite any FastMCP-into-FastAPI mount,
so the same three fixes apply. Kept parallel on purpose: fix one, fix them all.

SDK COMPATIBILITY: the modern transport is streamable HTTP
(`streamable_http_app()`); older SDKs had only SSE (`sse_app()`). The newer is
tried first.

Mounting MCP does NOT widen the listener. The kitchen still binds loopback by
default, and still refuses to start on a wider bind with no token.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import FastAPI
from starlette.routing import Route

logger = logging.getLogger(__name__)

# the two routes a mount adds, by name, so a second mount can take the first one's down
_MOUNT = "seren-kitchen-mcp"
_BARE = "seren-kitchen-mcp-bare"


class _Bare:
    """The mount path with no trailing slash, handed to the transport as its own root, the way the Mount
    hands it "/mcp/": same app, no redirect in between. (An ASGI app, not a function, so the route passes
    every method through.)"""

    def __init__(self, transport: Any, path: str) -> None:
        self.transport, self.path = transport, path

    async def __call__(self, scope, receive, send) -> None:
        root = scope.get("root_path", "") + self.path
        await self.transport({**scope, "root_path": root, "path": root + "/", "raw_path": (root + "/").encode()}, receive, send)


def mount_path() -> str:
    path = os.environ.get("SEREN_KITCHEN_MCP_MOUNT", "/mcp").rstrip("/")
    return path if path.startswith("/") else "/" + path


def mount_mcp_routes(app: FastAPI, impl: Any):
    """Mount the kitchen's MCP server onto the app, its tools bound to `impl` (a KitchenToolImpl on the live
    Store). Called from the lifespan, once the store is open, IF the [mcp] extra is installed: the import
    below raises ImportError otherwise, and app.py carries on without the mount.

    Returns the FastMCP instance. The caller MUST enter `mcp.session_manager.run()` for the app's lifetime:
    the streamable-HTTP transport's task group lives there (see app.py's lifespan). Where it was mounted is
    left on app.state.mcp_path.
    """
    # imported here, not at module top, so a missing `mcp` reaches app.py's try/except rather than breaking load
    from mcp.server.fastmcp import FastMCP

    from .tools import INSTRUCTIONS, register_tools

    path = mount_path()
    mcp = FastMCP("seren-kitchen", instructions=INSTRUCTIONS)
    register_tools(mcp, impl)

    # -- Footgun 1: the double /mcp --
    # streamable_http_app() serves at settings.streamable_http_path, which DEFAULTS to "/mcp". Mounted at "/mcp"
    # the real endpoint would land at "/mcp/mcp" and "/mcp" itself would 404. Push the sub-app's path to root.
    if hasattr(mcp.settings, "streamable_http_path"):
        mcp.settings.streamable_http_path = "/"

    # -- Footgun 3: the DNS-rebinding host check --
    # FastMCP's protection defaults to localhost-only and answers 421 to a client that reached the box by its
    # hostname. Off by default, like the rest of the family; SEREN_KITCHEN_MCP_ALLOWED_HOSTS re-arms it.
    if hasattr(mcp.settings, "transport_security"):
        _apply_transport_security(mcp)

    # An app's lifespan can run more than once (a test client entered twice): the mount from the run before
    # holds a session manager that has stopped, and would answer first.
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, "name", "") not in (_MOUNT, _BARE)]
    transport = _resolve_transport_app(mcp)
    # -- Footgun 4: the redirect --
    # A Mount at "/mcp" matches "/mcp/" and below, so "/mcp" itself is answered with a 307 to "/mcp/". A client
    # that follows it never notices; one that does not (or sits behind a proxy that rewrites the Location) just
    # fails to connect, at the address every doc tells it to use. The bare path gets a route of its own.
    app.router.routes.append(Route(path, _Bare(transport, path), name=_BARE))
    app.mount(path, transport, name=_MOUNT)
    app.state.mcp_path = path
    logger.info("[seren-kitchen] MCP server mounted at %s (%d tools)", path, _count_tools(mcp))

    # -- Footgun 2: a mounted sub-app's lifespan never runs --
    # Starlette does not fire it, and the session manager raises "Task group is not initialized" on the first
    # request without it. Returned so the app's own lifespan can run it.
    return mcp


def _apply_transport_security(mcp) -> None:
    """FastMCP's host check from env, OFF unless an allowlist is given."""
    try:
        from mcp.server.transport_security import TransportSecuritySettings
    except Exception as exc:  # noqa: BLE001 - an SDK without the module keeps its own default
        logger.info("[seren-kitchen] transport_security module unavailable (%s); leaving the SDK default", exc)
        return

    def _split(name: str) -> list[str]:
        return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]

    hosts = _split("SEREN_KITCHEN_MCP_ALLOWED_HOSTS")
    origins = _split("SEREN_KITCHEN_MCP_ALLOWED_ORIGINS")
    if hosts or origins:
        if not origins:
            origins = [f"http://{h}" for h in hosts] + [f"https://{h}" for h in hosts]
        mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=True,
                                                                    allowed_hosts=hosts, allowed_origins=origins)
        logger.info("[seren-kitchen] MCP host check ON; allowed_hosts=%s", hosts)
    else:
        mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        logger.info("[seren-kitchen] MCP host check OFF; set SEREN_KITCHEN_MCP_ALLOWED_HOSTS for an allowlist")


def _resolve_transport_app(mcp) -> Any:
    """The ASGI app for the MCP HTTP transport: streamable HTTP, then SSE for an older SDK."""
    for attr in ("streamable_http_app", "sse_app"):
        factory = getattr(mcp, attr, None)
        if callable(factory):
            logger.info("[seren-kitchen] MCP transport: %s", attr)
            return factory()
    try:
        import mcp as _pkg
        version = getattr(_pkg, "__version__", "unknown")
    except Exception:  # noqa: BLE001
        version = "unknown"
    raise RuntimeError(f"mcp SDK {version} has neither streamable_http_app nor sse_app on FastMCP; "
                       "pip install 'seren-kitchen[mcp]' for a version that does")


def _count_tools(mcp) -> int:
    """How many tools, for the startup line. The SDK promises no stable attribute; 0 when none answers."""
    manager = getattr(mcp, "_tool_manager", None)
    if manager is not None and hasattr(manager, "list_tools"):
        try:
            return len(list(manager.list_tools()))
        except Exception:  # noqa: BLE001
            pass
    return 0
