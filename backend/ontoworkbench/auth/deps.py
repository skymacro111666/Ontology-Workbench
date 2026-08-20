"""FastAPI dependency: resolve current user from bearer token."""

from __future__ import annotations

from uuid import UUID

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from ontoworkbench.auth.jwt import decode_token
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.observability.middleware import user_id_ctx
from ontoworkbench.server.envelope import ApiError, ErrorCode


def get_current_user(request: Request, session: Session = Depends(get_session)) -> User:
    """Resolve the bearer token to a User; 401 paths per spec §6."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise ApiError(ErrorCode.AUTH_REQUIRED, "Authentication required")
    user_id = decode_token(auth.removeprefix("Bearer "), request.app.state.settings.jwt_secret)
    if user_id is None:
        raise ApiError(ErrorCode.TOKEN_EXPIRED, "Token is invalid or expired")
    try:
        uid = UUID(user_id)
    except ValueError:
        uid = None
    user = UserRepository(session).get(uid) if uid else None
    if user is None:
        raise ApiError(ErrorCode.AUTH_REQUIRED, "Unknown user")
    user_id_ctx.set(str(user.id))
    return user
