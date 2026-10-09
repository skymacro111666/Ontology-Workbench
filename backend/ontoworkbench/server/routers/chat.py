"""Chat sessions REST + SSE stream (spec-2 §1).

Read-only AI assistant plumbing: multi-session persisted chat per
ontology. This module holds the four session REST endpoints; the SSE
POST (lazy create + streaming) extends it in a later task.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ontoworkbench.db.models import ChatSession, User
from ontoworkbench.db.repositories import ChatMessageRepository, ChatSessionRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.lint import _lint_owned

router = APIRouter(prefix="/api/v1/ontologies", tags=["chat"])


class RenameIn(BaseModel):
    """Rename body: the new title."""

    title: str = Field(min_length=1, max_length=128)


def _chat_owned(
    user: User, session: Session, ontology_id: str, sid: str
) -> tuple[UUID, ChatSession]:
    """Parse oid+sid and ownership-check both (uniform 404 otherwise)."""
    oid = _lint_owned(user, session, ontology_id)
    try:
        session_id = UUID(sid)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such session") from None
    row = ChatSessionRepository(session).get_owned(user.id, oid, session_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No such session")
    return oid, row


@router.get("/{ontology_id}/chat/sessions")
def list_sessions(
    ontology_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Sessions of this ontology, newest activity first."""
    oid = _lint_owned(user, session, ontology_id)
    rows = ChatSessionRepository(session).list_by_ontology(user.id, oid)
    return respond(
        [
            {
                "id": str(r.id),
                "title": r.title,
                "updatedAt": r.updated_at.isoformat(),
                # dynamic attr set by list_by_ontology's scalar subquery
                "messageCount": r.message_count,  # type: ignore[attr-defined]
            }
            for r in rows
        ]
    )


@router.put("/{ontology_id}/chat/sessions/{sid}")
def rename_session(
    ontology_id: str,
    sid: str,
    body: RenameIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Rename one session (touches updated_at via onupdate)."""
    _, row = _chat_owned(user, session, ontology_id, sid)
    ChatSessionRepository(session).rename(row, body.title)
    session.commit()
    return respond({"id": str(row.id), "title": row.title})


@router.delete("/{ontology_id}/chat/sessions/{sid}")
def delete_session(
    ontology_id: str,
    sid: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Delete one session and its messages."""
    oid, _ = _chat_owned(user, session, ontology_id, sid)
    ChatSessionRepository(session).delete(user.id, oid, UUID(sid))
    session.commit()
    return respond(message="deleted")


@router.get("/{ontology_id}/chat/sessions/{sid}/messages")
def list_messages(
    ontology_id: str,
    sid: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Full history of one session, oldest first.

    Tool rows' content is the stored JSON string — the frontend parses and
    re-renders the collapsed tool rows verbatim.
    """
    _, row = _chat_owned(user, session, ontology_id, sid)
    msgs = ChatMessageRepository(session).list_for(row.id)
    return respond(
        [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "createdAt": m.created_at.isoformat(),
            }
            for m in msgs
        ]
    )
