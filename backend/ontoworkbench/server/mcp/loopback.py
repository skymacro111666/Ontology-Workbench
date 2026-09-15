"""In-process REST loopback (spec §6): call our own routers, forward the bearer.

payload logic stays in exactly one place (the routers) — MCP never re-implements.
httpx ASGITransport: no network, no port, no second server.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from ontoworkbench.server.mcp.auth import bearer_ctx
from ontoworkbench.server.mcp.errors import LoopbackError


class Loopback:
    """Thin async client over the parent FastAPI app."""

    def __init__(self, app: FastAPI) -> None:
        """Store the parent app every tool call loops back into."""
        self._app = app

    async def call(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
    ) -> Any:
        """Return envelope data; raise LoopbackError for any non-OK envelope."""
        headers = {}
        if bearer := bearer_ctx.get():
            headers["Authorization"] = f"Bearer {bearer}"
        async with AsyncClient(transport=ASGITransport(app=self._app), base_url="http://ow") as c:
            r = await c.request(method, path, params=params, json=json_body, headers=headers)
        env = r.json()
        if env.get("code") != "OK":
            raise LoopbackError(
                env.get("code", "INTERNAL_ERROR"), env.get("message", ""), env.get("hint")
            )
        return env.get("data")
