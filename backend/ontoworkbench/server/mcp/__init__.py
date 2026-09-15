"""MCP sub-app (spec §4): MCP server over streamable HTTP behind a credential gate.

`maybe_mount_mcp` is the only entry point app.py touches. The SDK import is
lazy so a no-token boot (the common case) never pays for it.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI
from sqlalchemy.exc import SQLAlchemyError
from starlette.types import ASGIApp

from ontoworkbench.db.repositories import AgentTokenRepository
from ontoworkbench.db.session import sessionmaker_or_fail

_log = structlog.get_logger("ow.mcp")


def create_mcp_app(parent: FastAPI) -> ASGIApp:
    """Assemble the gated MCP ASGI app (tools registered separately in T8)."""
    from mcp.server.mcpserver import MCPServer
    from mcp.server.transport_security import TransportSecuritySettings

    from ontoworkbench.server.mcp.auth import CredentialGate
    from ontoworkbench.server.mcp.loopback import Loopback
    from ontoworkbench.server.mcp.tools import register_tools

    mcp = MCPServer("ow")
    # DNS-rebinding protection is off because the credential gate below
    # demands a Bearer agent token or JWT on every request — a browser or
    # rebinding attack carries no Authorization header and dies 401 before
    # the SDK ever sees it.
    asgi = mcp.streamable_http_app(
        streamable_http_path="/",
        stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    register_tools(mcp, Loopback(parent))
    return CredentialGate(asgi, parent)


def maybe_mount_mcp(app: FastAPI) -> None:
    """Mount /api/v1/mcp only when at least one agent token exists (spec §4)."""
    try:
        with sessionmaker_or_fail()() as session:
            tokens = AgentTokenRepository(session).count_any()
    except (RuntimeError, SQLAlchemyError) as exc:
        _log.warning("mcp.mount_skipped", reason=str(exc)[:120])
        return
    if tokens:
        asgi = create_mcp_app(app)
        app.mount("/api/v1/mcp", asgi)
        # The lifespan chain reads this back: mounts do not propagate
        # lifespans, so app.py runs the MCP session manager under its own.
        app.state.mcp_asgi = asgi
        _log.info("mcp.mounted", agent_tokens=tokens)
    else:
        _log.debug("mcp.not_mounted")
