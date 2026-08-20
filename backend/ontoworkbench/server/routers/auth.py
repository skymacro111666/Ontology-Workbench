"""Auth endpoints: one-shot setup, login, me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ontoworkbench.auth.deps import get_current_user
from ontoworkbench.auth.jwt import create_token
from ontoworkbench.auth.password import hash_password, verify_password
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Constant argon2 hash verified for unknown usernames so login always runs
# one argon2 verification — response time cannot reveal account existence.
_DUMMY_HASH = hash_password("ow-login-timing-equalizer")


class Creds(BaseModel):
    """Login/setup payload."""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


@router.post("/setup")
def setup(creds: Creds, session: Session = Depends(get_session)) -> dict:
    """Create the single admin account; refuses once any user exists."""
    users = UserRepository(session)
    if users.count() > 0:
        raise ApiError(ErrorCode.SETUP_DONE, "Setup already completed", hint="Log in instead.")
    user = users.create(creds.username, hash_password(creds.password))
    return respond({"id": str(user.id), "username": user.username})


@router.post("/login")
def login(creds: Creds, request: Request, session: Session = Depends(get_session)) -> dict:
    """Verify credentials and issue a 7-day JWT."""
    user = UserRepository(session).get_by_username(creds.username)
    password_ok = verify_password(creds.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not password_ok:
        raise ApiError(ErrorCode.AUTH_INVALID_CREDENTIALS, "Invalid username or password")
    token, exp = create_token(str(user.id), request.app.state.settings.jwt_secret)
    return respond({"token": token, "expires_at": exp.isoformat()})


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    """Echo the authenticated user."""
    return respond(
        {
            "id": str(user.id),
            "username": user.username,
            "created_at": user.created_at.isoformat(),
        }
    )
