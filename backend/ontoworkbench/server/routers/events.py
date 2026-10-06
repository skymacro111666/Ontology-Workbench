"""Registry read API — the operation journal feed (Phase 1: pull only)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ontoworkbench.db.models import MutationEvent, User
from ontoworkbench.db.repositories import MutationEventRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import respond
from ontoworkbench.server.routers.ontologies import _owned

router = APIRouter(prefix="/api/v1", tags=["events"])

DEFAULT_LIMIT = 50
MAX_LIMIT = 200


def _event_out(e: MutationEvent) -> dict:
    """One journal row as the wire shape (camelCase, house style)."""
    return {
        "id": e.id,
        "createdAt": e.created_at.isoformat() if e.created_at else None,
        "action": e.action,
        "origin": e.origin,
        "source": e.source,
        "detail": e.detail,
    }


@router.get("/ontologies/{ontology_id}/events")
def list_events(
    ontology_id: str,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    before_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Newest-first journal page; before_id is the cursor from nextBeforeId."""
    row = _owned(user, session, ontology_id)  # 404s on unknown / foreign oid
    items = MutationEventRepository(session).list_before(
        user_id=user.id, ontology_id=row.id, limit=limit, before_id=before_id
    )
    next_before_id = items[-1].id if len(items) == limit else None
    return respond({"items": [_event_out(e) for e in items], "nextBeforeId": next_before_id})
