"""Agent-token management (spec D12): human-JWT only; machine creds hit the allowlist 403."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.auth import agent_tokens
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import AgentTokenRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/v1/agent-tokens", tags=["agent-tokens"])

_audit = structlog.get_logger("ow.audit")


class TokenOut(BaseModel):
    """Listing row: label + display prefix; hash and plaintext never leave the DB."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: UUID
    label: str
    token_prefix: str
    created_at: datetime
    last_used_at: datetime | None = None


class CreateIn(BaseModel):
    """Label for a new machine credential."""

    label: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")


@router.post("", status_code=201)
def create_token(
    body: CreateIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Mint a token; the response is the ONLY time the plaintext is shown."""
    repo = AgentTokenRepository(session)
    if repo.get_by_label(user.id, body.label) is not None:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "label already exists")
    token = agent_tokens.mint()
    row = repo.create(user.id, body.label, agent_tokens.hash_token(token), token[:8])
    session.commit()
    _audit.info("agent_token.create", label=body.label, user_id=str(user.id))
    return respond({"label": row.label, "token": token})


@router.get("")
def list_tokens(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """The current user's tokens (owner-scoped)."""
    rows = AgentTokenRepository(session).list_by_user(user.id)
    return respond(
        [TokenOut.model_validate(r, from_attributes=True).model_dump(by_alias=True) for r in rows]
    )


@router.delete("/{token_id}")
def revoke_token(
    token_id: UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Hard delete; the next request with this token is 401 (no restart)."""
    if not AgentTokenRepository(session).delete(user.id, token_id):
        raise ApiError(ErrorCode.NOT_FOUND, "No such token")
    session.commit()
    _audit.info("agent_token.revoke", token_id=str(token_id), user_id=str(user.id))
    return respond()
