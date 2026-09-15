"""FastAPI dependency: resolve current user from bearer token.

Two credential types, one account subject (spec D11): JWT = human session
credential (full power), owag_ agent token = account machine credential
(scope: the read-only endpoint allowlist below — PAT semantics).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ontoworkbench.auth import agent_tokens
from ontoworkbench.auth.jwt import decode_token
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.observability.middleware import user_id_ctx
from ontoworkbench.server.envelope import ApiError, ErrorCode

# Machine credentials may only reach the endpoints behind the 10 MCP tools
# (spec §5). method + route-template exact match; humans are unrestricted.
AGENT_ALLOWED: frozenset[str] = frozenset(
    {
        "GET /api/v1/ontologies",
        "GET /api/v1/ontologies/{ontology_id}/meta",
        "GET /api/v1/ontologies/{ontology_id}/search",
        "GET /api/v1/ontologies/{ontology_id}/tree",
        "GET /api/v1/ontologies/{ontology_id}/entities/{eid:path}",
        "GET /api/v1/ontologies/{ontology_id}/entities/{eid:path}/instances",
        "GET /api/v1/ontologies/{ontology_id}/export/file",
        "POST /api/v1/ontologies/{ontology_id}/lint/run",
        "POST /api/v1/ontologies/{ontology_id}/validation/run",
        "POST /api/v1/ontologies/{ontology_id}/query",
    }
)


def _finish(request: Request, user: User) -> User:
    """Shared post-auth bookkeeping: state + contextvar for the access log."""
    request.state.user_id = str(user.id)
    user_id_ctx.set(str(user.id))
    return user


def _authenticate_agent_token(request: Request, session: Session, token: str) -> User:
    resolved = agent_tokens.resolve(session, token)
    if resolved is None:
        raise ApiError(ErrorCode.TOKEN_EXPIRED, "Token is invalid or expired")
    user, label = resolved
    route = request.scope.get("route")
    key = f"{request.method} {getattr(route, 'path', request.url.path)}"
    if key not in AGENT_ALLOWED:
        raise ApiError(
            ErrorCode.AGENT_FORBIDDEN,
            "Agent tokens are limited to allowlisted read endpoints",
        )
    request.state.agent_label = label
    request.state.credential = f"agent:{label}"
    return _finish(request, user)


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Resolve the bearer token (JWT or owag_ agent token) to a User; 401 paths per spec §6."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(ErrorCode.AUTH_REQUIRED, "Authentication required")
    token = auth.removeprefix("Bearer ")
    if token.startswith(agent_tokens.TOKEN_PREFIX):
        return _authenticate_agent_token(request, session, token)
    user_id = decode_token(token, request.app.state.settings.jwt_secret)
    if user_id is None:
        raise ApiError(ErrorCode.TOKEN_EXPIRED, "Token is invalid or expired")
    try:
        uid = UUID(user_id)
    except ValueError:
        uid = None
    user = UserRepository(session).get(uid) if uid else None
    if user is None:
        raise ApiError(ErrorCode.AUTH_REQUIRED, "Unknown user")
    request.state.credential = "jwt"
    return _finish(request, user)
