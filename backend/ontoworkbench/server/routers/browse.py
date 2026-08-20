"""Read APIs over stored ontologies: tree/entities/overview/search/raw."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from ontoworkbench.auth.deps import get_current_user
from ontoworkbench.core.indexes import Indexes, build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.parsing import parse_graph
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/ontologies", tags=["browse"])


def _loader(request: Request):
    """Build a cache-miss loader that re-parses the stored file."""
    store: LocalUserDirStore = request.app.state.store

    def load(row: Ontology) -> Indexes:
        data = store.read(Path(row.storage_path))
        return build_indexes(build_ir(parse_graph(data, row.format)))

    return load


def _owned(
    request: Request, user: User, ontology_id: str, session: Session
) -> tuple[Ontology, Indexes]:
    """Resolve an owned ontology and its (cached) indexes; uniform 404 otherwise."""
    try:
        oid = UUID(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid)
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return row, request.app.state.cache.indexes_for(row, _loader(request))


def _entity_or_404(ix: Indexes, eid: str):
    """Fetch an entity by eid; uniform NOT_FOUND envelope."""
    e = ix.entity(eid)
    if e is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No such entity")
    return e


@router.get("/{ontology_id}/tree")
def tree(
    ontology_id: str,
    request: Request,
    parent: str | None = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Direct children of parent (roots when omitted)."""
    _, ix = _owned(request, user, ontology_id, session)
    return respond([n.model_dump() for n in ix.tree(parent)])


@router.get("/{ontology_id}/entities/{eid:path}/neighbors")
def neighbors(
    ontology_id: str,
    eid: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Local graph view around one entity (registered before the greedy route)."""
    _, ix = _owned(request, user, ontology_id, session)
    _entity_or_404(ix, eid)
    return respond(ix.neighbors(eid))


@router.get("/{ontology_id}/entities/{eid:path}")
def entity(
    ontology_id: str,
    eid: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """One entity's page-shaped IR."""
    _, ix = _owned(request, user, ontology_id, session)
    return respond(_entity_or_404(ix, eid).model_dump())


@router.get("/{ontology_id}/overview")
def overview(
    ontology_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Bounded whole-graph view."""
    _, ix = _owned(request, user, ontology_id, session)
    return respond(ix.overview())


@router.get("/{ontology_id}/search")
def search(
    ontology_id: str,
    request: Request,
    q: str,
    limit: int = 20,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Search hits over localname/label/comment."""
    _, ix = _owned(request, user, ontology_id, session)
    return respond([h.model_dump() for h in ix.search(q, limit)])


@router.get("/{ontology_id}/raw/{eid:path}")
def raw(
    ontology_id: str,
    eid: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Raw Turtle of one entity's axioms."""
    _, ix = _owned(request, user, ontology_id, session)
    e = _entity_or_404(ix, eid)
    return respond({"turtle": "\n\n".join(a.turtle for a in e.axioms), "eid": e.eid})
