"""Chat sessions REST + SSE stream (spec-2 §1, §2).

Read-only AI assistant plumbing: multi-session persisted chat per
ontology. The four REST endpoints manage sessions; the SSE POST lazily
creates a session on the first successful send and streams the agent
loop's neutral events as SSE frames.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID

import pyoxigraph as ox
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.ai.types import ToolCall
from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.db.models import ChatMessage, ChatSession, Ontology, User
from ontoworkbench.db.repositories import ChatMessageRepository, ChatSessionRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.cache import OntologyCache, load_store
from ontoworkbench.server.chat.contextpack import build_system_prompt
from ontoworkbench.server.chat.loop import run_chat
from ontoworkbench.server.chat.tools import ChatToolContext
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.ai_settings import _merged_cfg, get_ai_provider
from ontoworkbench.server.routers.browse import _owned
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


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ChatIn(CamelModel):
    """Send body: an optional session id (None = lazy create) + content."""

    session_id: UUID | None = None
    content: str = Field(min_length=1, max_length=8000)


def _history_from_rows(rows: list[ChatMessage]) -> list[dict]:
    """Rebuild neutral loop history from persisted rows (spec-2 §4).

    Text rows pass through; consecutive tool rows (stored as
    {"name","ok","result"} JSON) regroup into one assistant tool_calls
    turn followed by their tool messages — the same shape the loop built.
    """
    out: list[dict] = []
    group: list[dict] = []

    def flush() -> None:
        if not group:
            return
        out.append(
            {
                "role": "assistant",
                "tool_calls": [ToolCall(name=g["name"], arguments={}) for g in group],
            }
        )
        for g in group:
            out.append({"role": "tool", "name": g["name"], "content": g.get("result", "")})
        group.clear()

    for m in rows:
        if m.role == "tool":
            try:
                parsed = json.loads(m.content)
            except ValueError:
                parsed = {"name": "tool", "result": m.content}
            group.append(
                parsed if isinstance(parsed, dict) else {"name": "tool", "result": str(parsed)}
            )
        else:
            flush()
            out.append({"role": m.role, "content": m.content})
    flush()
    return out


def sse(event: str, payload: dict) -> str:
    """One SSE frame (spec-2 §2's own protocol, decoupled from LLM wires)."""
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_chat(
    request: Request,
    user: User,
    db: Session,
    provider: ModelProvider,
    cfg,
    row: Ontology,
    ix,
    store: ox.Store,
    prefixes: PrefixMap,
    body: ChatIn,
    srow: ChatSession | None,
) -> AsyncIterator[str]:
    """One send: lazy session, streamed events, single end-of-turn commit.

    Everything stages in one transaction; an early failure rolls back so a
    failed first send leaves no session row (the Review-Focus promise).
    """
    srepo, mrepo = ChatSessionRepository(db), ChatMessageRepository(db)
    tool_sink: list[dict] = []
    text_acc = ""
    title_base = body.content[:30]
    try:
        if srow is None:
            srow = srepo.create(user.id, row.id, title_base)
        yield sse("session", {"sessionId": str(srow.id), "title": srow.title or title_base})

        history_rows = mrepo.list_for(srow.id)
        mrepo.append(srow.id, "user", body.content)
        history = _history_from_rows(history_rows)

        ctx = ChatToolContext(request=request, row=row, ix=ix, store=store, prefixes=prefixes)
        system = build_system_prompt(row, store, prefixes)
        async for event, payload in run_chat(
            provider, system, history, body.content, ctx, tool_sink=tool_sink
        ):
            if event == "done":
                payload = {**payload, "model": cfg.model}
            elif event == "delta":
                text_acc += payload.get("text", "")
            yield sse(event, payload)
            if await request.is_disconnected():
                break
    except (CoreError, ApiError) as e:
        # SSE bodies cannot switch to JSON mid-stream: the error rides as an
        # event; the uncommitted session/user rows roll away.
        db.rollback()
        yield sse("error", {"code": str(e.code), "message": e.message})
        return

    for t in tool_sink:
        mrepo.append(srow.id, "tool", json.dumps(t, ensure_ascii=False)[:8192])
    if text_acc:
        mrepo.append(srow.id, "assistant", text_acc)
    srepo.touch(srow)
    db.commit()


@router.post("/{ontology_id}/chat/messages")
async def post_message(
    ontology_id: str,
    body: ChatIn,
    request: Request,
    provider: ModelProvider = Depends(get_ai_provider),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """Send one message; the answer streams back as SSE events.

    Unconfigured AI and unknown session ids raise before the stream starts
    (envelope errors); mid-stream failures arrive as `error` events.
    """
    row, ix = _owned(request, user, ontology_id, session)
    srow: ChatSession | None = None
    if body.session_id is not None:
        srow = ChatSessionRepository(session).get_owned(user.id, row.id, body.session_id)
        if srow is None:
            raise ApiError(ErrorCode.NOT_FOUND, "No such session")
    cache: OntologyCache = request.app.state.cache
    store, prefixes = cache.store_for(row, load_store)
    cfg = _merged_cfg(request.app.state.settings, user.id, session)
    return StreamingResponse(
        _stream_chat(request, user, session, provider, cfg, row, ix, store, prefixes, body, srow),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
