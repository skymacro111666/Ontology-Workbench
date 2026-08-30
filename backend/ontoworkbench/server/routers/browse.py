"""Read APIs over stored ontologies: tree/entities/overview/search/raw."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.indexes import Indexes, build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.parsing import parse_graph
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/ontologies", tags=["browse"])


def _loader(request: Request):
    """Build a cache-miss loader that re-parses the stored file."""
    store: LocalUserDirStore = request.app.state.store

    def load(row: Ontology) -> Indexes:
        data = store.read(Path(row.storage_path))
        return build_indexes(build_ir(parse_graph(data, row.format)))

    return load


def _camel(value: Any) -> Any:
    """Recursively camelCase payload keys — the browse data contract.

    The golden file docs/api-examples/success-entity.json (contract baseline)
    serializes data payloads camelCase; core models stay snake_case and
    auth payloads stay snake_case (their briefs pin that casing).
    """
    if isinstance(value, dict):
        return {to_camel(k): _camel(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camel(v) for v in value]
    return value


def _owned_row(user: User, ontology_id: str, session: Session) -> Ontology:
    """Resolve an owned ontology row; uniform 404 otherwise (no parsing)."""
    try:
        oid = UUID(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid)
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return row


def _owned(
    request: Request, user: User, ontology_id: str, session: Session
) -> tuple[Ontology, Indexes]:
    """Resolve an owned ontology and its (cached) indexes; uniform 404 otherwise."""
    row = _owned_row(user, ontology_id, session)
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
    return respond(_camel([n.model_dump() for n in ix.tree(parent)]))


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
    return respond(_camel(ix.neighbors(eid)))


@router.get("/{ontology_id}/entities/{eid:path}/instances")
def instances(
    ontology_id: str,
    eid: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """A class's direct named individuals, canvas-shaped (badge reveal)."""
    _, ix = _owned(request, user, ontology_id, session)
    _entity_or_404(ix, eid)
    return respond(_camel(ix.instances(eid)))


@router.get("/{ontology_id}/entities/{eid:path}")
def entity(
    ontology_id: str,
    eid: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """One entity's page-shaped IR; named individuals dispatch to IndividualIR."""
    _, ix = _owned(request, user, ontology_id, session)
    e = ix.entity(eid)
    if e is not None:
        return respond(_camel(e.model_dump()))
    ind = ix.individual(eid)
    if ind is not None:
        return respond(_camel(ind.model_dump()))
    raise ApiError(ErrorCode.NOT_FOUND, "No such entity")


@router.get("/{ontology_id}/overview")
def overview(
    ontology_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Bounded whole-graph view."""
    _, ix = _owned(request, user, ontology_id, session)
    return respond(_camel(ix.overview()))


@router.get("/{ontology_id}/source")
def source(
    ontology_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """The ontology's source text, verbatim (workspace text view)."""
    row = _owned_row(user, ontology_id, session)
    store: LocalUserDirStore = request.app.state.store
    content = store.read(Path(row.storage_path)).decode("utf-8", errors="replace")
    return respond(
        {
            "filename": row.filename,
            "format": row.format,
            "content": content,
            "fileHash": row.file_hash,
        }
    )


@router.get("/{ontology_id}/assertion-schema")
def assertion_schema(
    ontology_id: str,
    request: Request,
    classes: str = Query(default=""),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Usable assertion properties for the comma-joined classes."""
    _, ix = _owned(request, user, ontology_id, session)
    want = [c for c in classes.split(",") if c]
    return respond(_camel([p.model_dump() for p in ix.assertion_schema(want)]))


@router.get("/{ontology_id}/assertion-edges")
def assertion_edges(
    ontology_id: str,
    request: Request,
    eids: str = Query(default=""),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Instance-to-instance assertion edges within the given set (cap 500)."""
    _, ix = _owned(request, user, ontology_id, session)
    want = [e for e in eids.split(",") if e]
    return respond(_camel(ix.assertion_edges(want)))


@router.get("/{ontology_id}/search")
def search(
    ontology_id: str,
    request: Request,
    q: str,
    limit: int = Query(default=20, ge=1),
    type: str | None = Query(default=None),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Search hits over localname/label/comment; individuals join as Instance."""
    _, ix = _owned(request, user, ontology_id, session)
    # Exact-match vocabulary in Indexes.search ('instance' → 'Instance');
    # first-letter-only — capitalize() would mangle 'ObjectProperty'.
    type_normalized = (type[:1].upper() + type[1:]) if type else None
    return respond(_camel([h.model_dump() for h in ix.search(q, limit, type_=type_normalized)]))


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
    return respond(_camel({"turtle": "\n\n".join(a.turtle for a in e.axioms), "eid": e.eid}))
