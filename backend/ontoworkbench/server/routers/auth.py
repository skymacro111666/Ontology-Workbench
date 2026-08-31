"""Auth endpoints: one-shot setup, login, me, password change."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.auth.jwt import create_token
from ontoworkbench.auth.password import hash_password, verify_password
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
def status(session: Session = Depends(get_session)) -> dict:
    """Whether first-run setup is still pending; needs no authentication."""
    need_setup = UserRepository(session).count() == 0
    return respond({"need_setup": need_setup})


# Constant argon2 hash verified for unknown usernames so login always runs
# one argon2 verification — response time cannot reveal account existence.
_DUMMY_HASH = hash_password("ow-login-timing-equalizer")


class Creds(BaseModel):
    """Login/setup payload."""

    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


@router.post("/setup")
def setup(creds: Creds, request: Request, session: Session = Depends(get_session)) -> dict:
    """Create the single admin account; refuses once any user exists."""
    users = UserRepository(session)
    if users.count() > 0:
        raise ApiError(ErrorCode.SETUP_DONE, "Setup already completed", hint="Log in instead.")
    user = users.create(creds.username, hash_password(creds.password))
    request.state.user_id = str(user.id)
    return respond({"id": str(user.id), "username": user.username})


@router.post("/login")
def login(creds: Creds, request: Request, session: Session = Depends(get_session)) -> dict:
    """Verify credentials and issue a 7-day JWT."""
    user = UserRepository(session).get_by_username(creds.username)
    password_ok = verify_password(creds.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not password_ok:
        raise ApiError(ErrorCode.AUTH_INVALID_CREDENTIALS, "Invalid username or password")
    request.state.user_id = str(user.id)  # the acting user, for the access log
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


class PasswordChange(BaseModel):
    """Change-password payload (camelCase wire names)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


@router.put("/password")
def change_password(
    body: PasswordChange,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Verify the current password and set a new one.

    Tokens issued before the change stay valid until their 7-day expiry
    (keep-logged-in design for the single-user self-hosted deployment).
    """
    if not verify_password(body.current_password, user.password_hash):
        raise ApiError(ErrorCode.AUTH_INVALID_CREDENTIALS, "Current password is incorrect")
    UserRepository(session).update_password(user.id, hash_password(body.new_password))
    return respond({"ok": True})
