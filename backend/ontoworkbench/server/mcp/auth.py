"""Outer gate (spec §5): agent token or human JWT; no second secret leaves the env."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any
from uuid import UUID

from fastapi import FastAPI
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import Receive, Scope, Send

from ontoworkbench.auth import agent_tokens
from ontoworkbench.auth.jwt import decode_token
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import sessionmaker_or_fail
from ontoworkbench.server.envelope import ErrorCode, error_body

# The loopback forwards the ORIGINAL bearer; tools read it from here (the
# spike proved contextvars propagate from ASGI middleware into tool bodies).
bearer_ctx: ContextVar[str | None] = ContextVar("ow_mcp_bearer", default=None)
label_ctx: ContextVar[str | None] = ContextVar("ow_mcp_label", default=None)


def _header(scope: Scope, name: str) -> str:
    """Return a request header by lowercase name, or '' when absent."""
    for key, value in scope.get("headers", []):
        if key.decode().lower() == name:
            return value.decode()
    return ""


class CredentialGate:
    """ASGI middleware: validate the Authorization header before the MCP app.

    The parent app arrives by construction (not via scope["app"]): the JWT
    fallback reads its settings.jwt_secret directly.
    """

    def __init__(self, app: Starlette, parent: FastAPI) -> None:
        """Store the wrapped MCP app and the parent FastAPI app."""
        self._app = app
        self._parent = parent

    @property
    def router(self) -> Any:
        """The wrapped Starlette router — app.py chains its lifespan through here."""
        return self._app.router

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Let only bearer-authenticated requests reach the MCP app."""
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        auth = _header(scope, "authorization")
        ok, label, user_id = False, None, None
        credential: str | None = None
        if auth.startswith("Bearer "):
            token = auth.removeprefix("Bearer ")
            with sessionmaker_or_fail()() as session:
                resolved = agent_tokens.resolve(session, token)
                if resolved is not None:
                    user, label = resolved
                    user_id, ok = str(user.id), True
                    credential = f"agent:{label}"
                else:
                    uid = decode_token(token, self._parent.state.settings.jwt_secret)
                    if uid:
                        jwt_user = UserRepository(session).get(UUID(uid))
                        if jwt_user is not None:
                            user_id, ok, credential = str(jwt_user.id), True, "jwt"
        if not ok:
            response = JSONResponse(
                status_code=401,
                content=error_body(ErrorCode.AUTH_REQUIRED, "Authentication required"),
            )
            await response(scope, receive, send)
            return
        # scope["state"] is what request.state reads in the access log middleware.
        state: dict[str, Any] = scope.setdefault("state", {})
        state["user_id"] = user_id
        if label:
            state["agent_label"] = label
        state["credential"] = credential
        b = bearer_ctx.set(auth.removeprefix("Bearer "))
        ell = label_ctx.set(label)
        try:
            await self._app(scope, receive, send)
        finally:
            bearer_ctx.reset(b)
            label_ctx.reset(ell)
