"""Read APIs over stored ontologies: tree/entities/overview/search/raw."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Query, Request
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.indexes import DEPRECATED_BUCKET, Indexes, build_indexes
from ontoworkbench.core.ir import IRBundle, build_ir_store
from ontoworkbench.core.ir_cache import read_ir_cache, write_ir_cache
from ontoworkbench.core.owl2.render import entity_manchester
from ontoworkbench.core.parsing import timed_parse_store
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session, sessionmaker_or_fail
from ontoworkbench.observability.metrics import (
    ow_build_seconds,
    ow_ir_cache_reads_total,
    ow_parse_seconds,
)
from ontoworkbench.server.cache import load_store
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/ontologies", tags=["browse"])

_log = structlog.get_logger("ow.cache")


def _heal_row(row: Ontology, data: bytes, disk_hash: str, ir: IRBundle) -> None:
    """Catch the DB row up after an external edit (方案三 self-heal).

    The file is the single source of truth: when the disk hash moved on
    from the row's, the row records the healed facts. Failure degrades to
    a warning — the read itself is already valid.
    """
    if row.file_hash == disk_hash:
        return
    stats = dict(row.stats_json or {})
    stats["prefixes"] = ir.prefixes
    try:
        with sessionmaker_or_fail()() as db:
            OntologyRepository(db).update(
                row.id,
                class_count=ir.counts.class_count,
                property_count=ir.counts.property_count,
                axiom_count=ir.counts.axiom_count,
                instance_count=ir.counts.individual_count,
                stats_json=stats,
                file_size_bytes=len(data),
                file_hash=disk_hash,
            )
    except Exception as exc:
        _log.warning(
            "browse.self_heal_failed",
            ontology_id=str(row.id),
            error_type=type(exc).__name__,
        )
        return
    # Keep the request-scoped row (and the memory-cache key indexes_for
    # stores right after the loader returns) on the healed values.
    row.file_hash = disk_hash
    row.file_size_bytes = len(data)
    row.class_count = ir.counts.class_count
    row.property_count = ir.counts.property_count
    row.axiom_count = ir.counts.axiom_count
    row.instance_count = ir.counts.individual_count
    row.stats_json = stats
    _log.info(
        "browse.self_heal",
        ontology_id=str(row.id),
        file_size_bytes=len(data),
    )


def _loader(request: Request):
    """Build a cache-miss loader: disk IR cache first, re-parse as fallback.

    The pkl validates against the CURRENT disk hash, not the DB row's
    (方案三: an external edit — vim/rsync/Protégé — must never serve
    stale); a mismatch re-parses, re-keys the pkl and heals the row. A
    hit still skips parse+build_ir_store entirely (restart recovery for
    big ontologies).
    """
    store: LocalUserDirStore = request.app.state.store

    def load(row: Ontology) -> Indexes:
        path = Path(row.storage_path)
        data = store.read(path)
        disk_hash = LocalUserDirStore.file_hash(data)
        cached = read_ir_cache(path, disk_hash)
        ow_ir_cache_reads_total.labels(cached.outcome).inc()
        if cached.ir is not None:
            _heal_row(row, data, disk_hash, cached.ir)
            return build_indexes(cached.ir)
        with ow_parse_seconds.labels(row.format).time():
            ox_store, prefixes, _ = timed_parse_store(data, row.format)
        with ow_build_seconds.time():
            ir = build_ir_store(ox_store, prefixes)
        write_ir_cache(path, ir, disk_hash)
        _heal_row(row, data, disk_hash, ir)
        return build_indexes(ir)

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
    includeDeprecated: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Direct children of parent (roots when omitted).

    Deprecated classes are hidden unless includeDeprecated (spec §4).
    """
    _, ix = _owned(request, user, ontology_id, session)
    return respond(
        _camel([n.model_dump() for n in ix.tree(parent, include_deprecated=includeDeprecated)])
    )


@router.get("/{ontology_id}/entities/{eid:path}/expand")
def expand(
    ontology_id: str,
    eid: str,
    request: Request,
    includeDeprecated: bool = False,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Progressive-canvas drill-down: live children (with subtree sizes) or a bucket."""
    _, ix = _owned(request, user, ontology_id, session)
    if eid != DEPRECATED_BUCKET and not eid.startswith("__prefix__:"):
        _entity_or_404(ix, eid)
    return respond(_camel(ix.expand(eid, include_deprecated=includeDeprecated)))


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
    """One entity's page-shaped IR; named individuals dispatch to IndividualIR.

    Manchester rendering is lazy per request (OWL 2 M1): a shallow copy
    carries it, the cached EntityIR stays pristine. Any bridge failure
    degrades to manchester=None — the axioms payload is never at risk.
    """
    row, ix = _owned(request, user, ontology_id, session)
    e = ix.entity(eid)
    if e is not None:
        manchester = None
        try:
            store, prefixes = request.app.state.cache.store_for(row, load_store)
            manchester = entity_manchester(store, eid, prefixes)
        except Exception:  # 桥失败/超预算一律降级,详情页永不因渲染阻塞
            manchester = None
        out = e.model_copy(update={"manchester": manchester})
        return respond(_camel(out.model_dump()))
    ind = ix.individual(eid)
    if ind is not None:
        return respond(_camel(ind.model_dump()))
    raise ApiError(ErrorCode.NOT_FOUND, "No such entity")


@router.get("/{ontology_id}/overview")
def overview(
    ontology_id: str,
    request: Request,
    includeDeprecated: bool = False,
    view: str = "auto",
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Tiered whole-graph view (auto|full|progressive); deprecated hidden unless opted in."""
    _, ix = _owned(request, user, ontology_id, session)
    if view not in ("auto", "full", "progressive"):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "view must be one of auto, full, progressive")
    return respond(_camel(ix.overview(include_deprecated=includeDeprecated, view=view)))


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
