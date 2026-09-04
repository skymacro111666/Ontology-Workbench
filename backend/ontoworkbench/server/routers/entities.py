"""Store-side entity editing (A2): create classes/properties, edit, delete.

Each write mutates the ontology's pooled pyoxigraph Store (parsed once
per file version — see OntologyCache.store_for), then walks the A1
persistence pipeline (serialize → atomic write → row/cache refresh).
Optimistic lock via baseFileHash on every mutation, exactly like
PUT /source (design spec 2026-08-26 §4). instances.py rides the same
pipeline; lint.py reads the same pool without ever mutating it.

Pool discipline: mutations land in the SHARED cached Store, so the
_edit_store checkout is a context manager that evicts the entry when a
request dies between checkout and _persist (a 422 on a later field, an
unexpected error) — otherwise the refused edit would ride along with
the next successful write. _persist keeps its own guard for its
internal failures; handlers still validate before mutating where they
can (keeps requests all-or-nothing in memory), but correctness never
depends on that ordering.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import pyoxigraph as ox
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pyoxigraph import Store
from sqlalchemy.orm import Session

from ontoworkbench.core import terms
from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import IRBundle, build_ir_store
from ontoworkbench.core.ir_cache import write_ir_cache
from ontoworkbench.core.parsing import serialize_store
from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.observability.metrics import ow_build_seconds, ow_uploads_total
from ontoworkbench.server.cache import OntologyCache, load_store
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.ontologies import (
    MAX_UPLOAD,
    meta_of,
    title_of_store,
)

router = APIRouter(prefix="/api", tags=["entities"])

_NAME_RE = re.compile(r"^[A-Za-z_][\w.-]*$")


class CamelModel(BaseModel):
    """Base model serializing snake_case fields as camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class LabelInput(CamelModel):
    """One localized rdfs:label value; empty lang writes a plain literal."""

    value: str
    lang: str | None = None


class ClassCreate(CamelModel):
    """POST /classes body: new class (a subclass when parents is set)."""

    name: str
    prefix: str
    label: LabelInput | None = None
    comment: str | None = None
    parents: list[str] = Field(default_factory=list)
    base_file_hash: str


class PropertyCreate(CamelModel):
    """POST /properties body: object or datatype property."""

    name: str
    prefix: str
    ptype: str  # ObjectProperty | DatatypeProperty
    label: LabelInput | None = None
    comment: str | None = None
    domains: list[str] = Field(default_factory=list)
    ranges: list[str] = Field(default_factory=list)
    base_file_hash: str


class EntityUpdate(CamelModel):
    """PUT /entities body: absent keys stay untouched, null/[] clears."""

    label: LabelInput | None = None
    comment: str | None = None
    parents: list[str] | None = None
    domains: list[str] | None = None
    ranges: list[str] | None = None
    base_file_hash: str


def _owned_row(user: User, session: Session, ontology_id: str) -> Ontology:
    """Resolve an owned ontology row or raise the uniform 404."""
    try:
        oid = UUID(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid)
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return row


def _check_lock(body_hash: str, row: Ontology) -> None:
    """Reject stale baseFileHash before touching anything."""
    if body_hash != row.file_hash:
        raise ApiError(
            ErrorCode.EDIT_CONFLICT,
            "The file changed since it was loaded",
            "Reload the graph and retry the edit on the current version.",
        )


@contextmanager
def _edit_store(request: Request, row: Ontology) -> Iterator[tuple[Store, PrefixMap]]:
    """Check out the pooled editable Store; evict it if the request dies.

    Mutations land in the SHARED cached instance (parse-free on repeat
    edits), so any exception between checkout and _persist — a 422 on a
    later field, an unexpected error — must drop the entry: the Store
    may already carry part of the refused edit while the file never
    changed. The next edit re-parses disk truth. _persist keeps its own
    guard for failures inside the write pipeline; this one makes the
    no-dirty-entry invariant structural for every write endpoint.
    """
    cache: OntologyCache = request.app.state.cache
    store, prefixes = cache.store_for(row, load_store)
    try:
        yield store, prefixes
    except Exception:
        cache.drop_store(str(row.id))
        raise


def _iri_for(ns: PrefixMap, prefix: str, name: str) -> str:
    """Mint prefix:name; unknown prefix or bad name is a 422."""
    if not _NAME_RE.match(name):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid name '{name}'",
            "Use a letter/underscore start, then letters, digits, ., - or _.",
        )
    iri = ns.iri_for(prefix, name)
    if iri is not None:
        return iri
    known = ", ".join(ns.known_prefixes()) or "(none)"
    raise ApiError(
        ErrorCode.VALIDATION_ERROR,
        f"Unknown prefix '{prefix}'",
        f"Known prefixes: {known}",
    ) from None


def _iri_or_422(value: str) -> ox.NamedNode:
    """A user-supplied IRI (parents/domains/ranges); bad lexical form is a 422."""
    try:
        return ox.NamedNode(value)
    except ValueError:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid IRI '{value}'",
            "Parents, domains, and ranges must be absolute IRIs.",
        ) from None


def _reject_duplicate(store: Store, iri: str) -> None:
    """Refuse to mint an IRI that already carries triples."""
    node = ox.NamedNode(iri)
    used = (
        next(store.quads_for_pattern(node, None, None, ox.DefaultGraph()), None) is not None
        or next(store.quads_for_pattern(None, None, node, ox.DefaultGraph()), None) is not None
    )
    if used:
        raise ApiError(
            ErrorCode.DUPLICATE_ENTITY,
            f"'{iri}' is already used in this ontology",
            "Pick a different name or prefix.",
        )


def _quad(s: ox.NamedNode, p: ox.NamedNode, o: ox.NamedNode | ox.Literal) -> ox.Quad:
    """A default-graph quad (the editing pipeline is graph-name-free)."""
    return ox.Quad(s, p, o, ox.DefaultGraph())


def _remove_all(store: Store, s: ox.NamedNode, p: ox.NamedNode) -> None:
    """Drop every (s, p, *) quad from the default graph."""
    for q in list(store.quads_for_pattern(s, p, None, ox.DefaultGraph())):
        store.remove(q)


def _set_label(store: Store, ent: ox.NamedNode, label: LabelInput | None) -> None:
    """Replace all rdfs:label values with the one given (None clears)."""
    _remove_all(store, ent, terms.RDFS_LABEL)
    if label and label.value:
        lit = (
            ox.Literal(label.value, language=label.lang) if label.lang else ox.Literal(label.value)
        )
        store.add(_quad(ent, terms.RDFS_LABEL, lit))


def _set_comment(store: Store, ent: ox.NamedNode, comment: str | None) -> None:
    """Replace all rdfs:comment values (None clears)."""
    _remove_all(store, ent, terms.RDFS_COMMENT)
    if comment:
        store.add(_quad(ent, terms.RDFS_COMMENT, ox.Literal(comment)))


def _set_uriref_objects(
    store: Store, ent: ox.NamedNode, pred: ox.NamedNode, values: list[str] | None
) -> None:
    """Replace pred objects, keeping blank-node axioms (owl:Restriction etc.).

    Only IRI objects are removed: rdfs:subClassOf restrictions live in
    blank nodes and must survive reparenting untouched.
    """
    # Validate every IRI before touching the store: a mid-list failure must
    # leave nothing half-applied.
    nodes = [_iri_or_422(v) for v in values or []]
    named = [
        q
        for q in store.quads_for_pattern(ent, pred, None, ox.DefaultGraph())
        if isinstance(q.object, ox.NamedNode)
    ]
    for q in named:
        store.remove(q)
    for node in nodes:
        store.add(_quad(ent, pred, node))


def _entity_payload(ns: PrefixMap, iri: str, kind: str) -> dict[str, str]:
    """Small entity reference for write responses (full data via GET)."""
    pair = ns.curie_for(str(iri))
    curie = f"{pair[0]}:{pair[1]}" if pair else str(iri)
    return {"eid": str(iri), "curie": curie, "type": kind}


def _persist(
    request: Request, session: Session, row: Ontology, store: Store, prefixes: PrefixMap
) -> tuple[Ontology, IRBundle]:
    """Serialize → build from the mutated store → atomic write → row/cache refresh.

    Any failure evicts the pooled Store entry: it already carries this
    edit while the file never changed, so serving it again would silently
    land the edit inside the next write.
    """
    cache: OntologyCache = request.app.state.cache
    try:
        data = serialize_store(store, prefixes, row.format)
        if len(data) > MAX_UPLOAD:
            ow_uploads_total.labels("too_large").inc()
            raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
        # The mutated in-memory store IS the data just serialized — building the
        # IR from it directly drops the old re-parse-for-validation (a full
        # second parse per edit, ~3min on a 130MB ontology).
        old_parse_ms = (row.stats_json or {}).get("parse_ms")
        t0 = time.perf_counter()
        with ow_build_seconds.time():
            ir = build_ir_store(store, prefixes)
        build_ms = (time.perf_counter() - t0) * 1000.0

        dir_store: LocalUserDirStore = request.app.state.store
        dir_store.save(row.owner_user_id, UUID(str(row.id)), row.filename, data)
        repos = OntologyRepository(session)
        row = (
            repos.update(
                row.id,
                title=title_of_store(store, row.filename),
                class_count=ir.counts.class_count,
                property_count=ir.counts.property_count,
                axiom_count=ir.counts.axiom_count,
                instance_count=ir.counts.individual_count,
                stats_json={
                    "prefixes": ir.prefixes,
                    "parse_ms": old_parse_ms,
                    "build_ms": round(build_ms, 1),
                },
                file_size_bytes=len(data),
                file_hash=LocalUserDirStore.file_hash(data),
            )
            or row
        )
        # The disk cache must move with the file: the next cold start would
        # otherwise re-pay the full parse for this ontology.
        write_ir_cache(Path(row.storage_path), ir, row.file_hash)
        cache.indexes_for(row, lambda r: build_indexes(ir))
    except Exception:
        cache.drop_store(str(row.id))
        raise
    cache.refresh_store(row, store, prefixes)
    return row, ir


def _declared(store: Store, eid: str) -> ox.NamedNode:
    """The entity IRI, verified declared (typed) in the store, else 404."""
    try:
        iri = ox.NamedNode(eid)
    except ValueError:
        # A non-IRI path can never name a declared entity (parity with the
        # old 404 on unmatched terms).
        raise ApiError(ErrorCode.NOT_FOUND, "No such entity in this ontology") from None
    if next(store.quads_for_pattern(iri, terms.RDF_TYPE, None, ox.DefaultGraph()), None) is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No such entity in this ontology")
    return iri


def _kind_of(store: Store, iri: ox.NamedNode) -> str:
    """Class or property (for the response payload)."""
    typed = next(
        store.quads_for_pattern(iri, terms.RDF_TYPE, terms.OWL_CLASS, ox.DefaultGraph()), None
    )
    return "Class" if typed is not None else "Property"


@router.post("/ontologies/{ontology_id}/classes")
def create_class(
    ontology_id: str,
    body: ClassCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Create a class (with optional parents → subclass) in the stored file."""
    row = _owned_row(user, session, ontology_id)
    _check_lock(body.base_file_hash, row)
    with _edit_store(request, row) as (store, prefixes):
        iri = _iri_for(prefixes, body.prefix, body.name)
        _reject_duplicate(store, iri)
        parents = [_iri_or_422(p) for p in body.parents]
        ent = ox.NamedNode(iri)
        store.add(_quad(ent, terms.RDF_TYPE, terms.OWL_CLASS))
        _set_label(store, ent, body.label)
        _set_comment(store, ent, body.comment)
        for parent in parents:
            store.add(_quad(ent, terms.RDFS_SUBCLASSOF, parent))
        row, _ = _persist(request, session, row, store, prefixes)
        return respond({"meta": meta_of(row), "entity": _entity_payload(prefixes, iri, "Class")})


@router.post("/ontologies/{ontology_id}/properties")
def create_property(
    ontology_id: str,
    body: PropertyCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Create an object or datatype property with domain/range wiring."""
    if body.ptype not in ("ObjectProperty", "DatatypeProperty"):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "ptype must be ObjectProperty or DatatypeProperty"
        )
    row = _owned_row(user, session, ontology_id)
    _check_lock(body.base_file_hash, row)
    with _edit_store(request, row) as (store, prefixes):
        iri = _iri_for(prefixes, body.prefix, body.name)
        _reject_duplicate(store, iri)
        domains = [_iri_or_422(d) for d in body.domains]
        ranges = [_iri_or_422(r) for r in body.ranges]
        ent = ox.NamedNode(iri)
        ptype = (
            terms.OWL_OBJECTPROPERTY
            if body.ptype == "ObjectProperty"
            else terms.OWL_DATATYPEPROPERTY
        )
        store.add(_quad(ent, terms.RDF_TYPE, ptype))
        _set_label(store, ent, body.label)
        _set_comment(store, ent, body.comment)
        for d in domains:
            store.add(_quad(ent, terms.RDFS_DOMAIN, d))
        for r in ranges:
            store.add(_quad(ent, terms.RDFS_RANGE, r))
        row, _ = _persist(request, session, row, store, prefixes)
        return respond({"meta": meta_of(row), "entity": _entity_payload(prefixes, iri, "Property")})


@router.put("/ontologies/{ontology_id}/entities/{eid:path}")
def update_entity(
    ontology_id: str,
    eid: str,
    body: EntityUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Edit label/comment/parents/domains/ranges; absent keys unchanged."""
    row = _owned_row(user, session, ontology_id)
    _check_lock(body.base_file_hash, row)
    with _edit_store(request, row) as (store, prefixes):
        ent = _declared(store, eid)
        kind = _kind_of(store, ent)
        touched = body.model_fields_set
        if "label" in touched:
            _set_label(store, ent, body.label)
        if "comment" in touched:
            _set_comment(store, ent, body.comment)
        if "parents" in touched and body.parents is not None:
            _set_uriref_objects(store, ent, terms.RDFS_SUBCLASSOF, body.parents)
        if "domains" in touched and body.domains is not None:
            _set_uriref_objects(store, ent, terms.RDFS_DOMAIN, body.domains)
        if "ranges" in touched and body.ranges is not None:
            _set_uriref_objects(store, ent, terms.RDFS_RANGE, body.ranges)
        row, _ = _persist(request, session, row, store, prefixes)
        return respond({"meta": meta_of(row), "entity": _entity_payload(prefixes, ent.value, kind)})


@router.delete("/ontologies/{ontology_id}/entities/{eid:path}")
def delete_entity(
    ontology_id: str,
    eid: str,
    baseFileHash: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    prune: bool = True,
) -> dict:
    """Delete an entity's triples; prune also drops reverse references.

    Pruned: subclasses' subClassOf → it, properties' domain/range → it,
    instances' rdf:type → it (they lose the type and leave the canvas).
    """
    row = _owned_row(user, session, ontology_id)
    _check_lock(baseFileHash, row)
    with _edit_store(request, row) as (store, prefixes):
        iri = _declared(store, eid)
        removed = 0
        for q in list(store.quads_for_pattern(iri, None, None, ox.DefaultGraph())):
            store.remove(q)
            removed += 1
        if prune:
            preds = (terms.RDFS_SUBCLASSOF, terms.RDFS_DOMAIN, terms.RDFS_RANGE, terms.RDF_TYPE)
            for pred in preds:
                for q in list(store.quads_for_pattern(None, pred, iri, ox.DefaultGraph())):
                    store.remove(q)
                    removed += 1
        row, _ = _persist(request, session, row, store, prefixes)
        return respond({"removed": removed, "meta": meta_of(row)})
