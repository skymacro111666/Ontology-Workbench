"""Store-side entity editing (A2): create classes/properties, edit, delete.

Y-axis commit path (2026-09-05): each write mutates the pooled
pyoxigraph Store, patches the cached IR IN PLACE under a per-oid
mutation lock, bumps the revision and returns in milliseconds — the
file lands later via the debounced AutosaveManager. Read endpoints
serve the same patched Indexes, so they see the edit at once
(read-your-writes) with no file round-trip.

Optimistic lock via baseRevision on every mutation: the revision moves
the moment an edit commits, unlike file_hash which only moves when the
debounced save lands. instances.py rides the same _commit_mutation path
(instance_eid + individual_delta); PUT /source keeps its baseFileHash
lock and its own write path; lint.py reads the same pool without ever
mutating it.

Pool discipline: mutations land in the SHARED cached Store, so the
_edit_store checkout is a context manager that evicts the entry when a
request dies between checkout and commit (a 422 on a later field, an
unexpected error) — otherwise the refused edit would ride along with
the next successful write. _commit_mutation carries the matching guard
for failures inside the IR patch itself (the cached Indexes may carry a
partial patch while the file never moved).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
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
from ontoworkbench.core.indexes import Indexes, build_indexes
from ontoworkbench.core.ir import (
    IRBundle,
    affected_around,
    build_ir_store,
    refresh_entities,
    refresh_individual,
)
from ontoworkbench.core.ir_cache import write_ir_cache
from ontoworkbench.core.parsing import serialize_store
from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session, sessionmaker_or_fail
from ontoworkbench.observability.metrics import ow_uploads_total
from ontoworkbench.server.cache import OntologyCache, load_store
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.ontologies import (
    MAX_UPLOAD,
    meta_with_state,
    title_of_store,
)

router = APIRouter(prefix="/api/v1", tags=["entities"])

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
    base_revision: int


class PropertyCreate(CamelModel):
    """POST /properties body: object or datatype property."""

    name: str
    prefix: str
    ptype: str  # ObjectProperty | DatatypeProperty
    label: LabelInput | None = None
    comment: str | None = None
    domains: list[str] = Field(default_factory=list)
    ranges: list[str] = Field(default_factory=list)
    base_revision: int


class EntityUpdate(CamelModel):
    """PUT /entities body: absent keys stay untouched, null/[] clears."""

    label: LabelInput | None = None
    comment: str | None = None
    parents: list[str] | None = None
    domains: list[str] | None = None
    ranges: list[str] | None = None
    base_revision: int


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


def _check_revision(base_revision: int, row: Ontology) -> None:
    """Reject stale baseRevision before touching anything.

    The revision moves on every committed edit — immediately, unlike
    file_hash which only moves when the debounced save lands — so this is
    the lock every Y-axis mutation checks.
    """
    if base_revision != row.revision:
        raise ApiError(
            ErrorCode.EDIT_CONFLICT,
            "The ontology changed since it was loaded",
            "Reload the graph and retry the edit on the current version.",
        )


@contextmanager
def _edit_store(request: Request, row: Ontology) -> Iterator[tuple[Store, PrefixMap]]:
    """Check out the pooled editable Store; evict it only on unexpected errors.

    Mutations land in the SHARED cached instance (parse-free on repeat
    edits). Validation refusals (ApiError) fire before the first mutation
    (validate-then-mutate, enforced per handler), so the Store stays
    clean and MUST stay pooled: dropping it would make the next edit
    re-parse the stale disk file and silently lose the still-pending
    autosave edits. Anything else escaping mid-mutation leaves an
    unknown half-applied state the pending autosave would serialize —
    drop the entry so the next edit re-parses disk truth.
    """
    cache: OntologyCache = request.app.state.cache
    store, prefixes = cache.store_for(row, load_store)
    try:
        yield store, prefixes
    except ApiError:
        raise  # refused before any mutation — the pooled Store is clean
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
    # "" is the default namespace (pizza-style `@prefix :`); display it as ":"
    known = ", ".join(p or ":" for p in ns.known_prefixes()) or "(none)"
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


def _axiom_count(store: Store) -> int:
    """Default-graph triple count (same query as build_ir_store's count)."""
    results = store.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
    assert isinstance(results, ox.QuerySolutions)
    return int(next(iter(results))["c"].value)


def _live_indexes(request: Request, row: Ontology, store: Store, prefixes: PrefixMap) -> Indexes:
    """The cached (already-patched) Indexes; full build from the Store on a miss.

    The miss is the first-edit cold path (or recovery after a source
    replace): indexes_for validates by file_hash/mtime, so while edits
    stay in memory every call hits the entry the previous mutation
    patched in place.
    """
    cache: OntologyCache = request.app.state.cache
    return cache.indexes_for(row, lambda r: build_indexes(build_ir_store(store, prefixes)))


def _commit_mutation(
    request: Request,
    session: Session,
    row: Ontology,
    store: Store,
    prefixes: PrefixMap,
    eid: str,
    *,
    class_delta: int = 0,
    prop_delta: int = 0,
    individual_delta: int = 0,
    instance_eid: str | None = None,
) -> Ontology:
    """Patch the live IR under the mutation lock, bump revision, debounce save.

    The millisecond-scale critical section is [IR patch + children
    rebuild + gen bump]; counts move with the caller's deltas (Task 5's
    refresh never touches them) and the DB row + autosave schedule land
    after the lock. instance_eid routes an individual's re-typing
    through refresh_individual — refresh_entities' cascade only
    discovers individuals from the current store, so handlers changing
    an individual's class links must name it (used by instances.py).
    """
    cache: OntologyCache = request.app.state.cache
    oid = str(row.id)
    ir: IRBundle
    try:
        with cache.mutation_lock(oid):
            ix = _live_indexes(request, row, store, prefixes)
            ir = ix.ir
            if class_delta:
                ir.counts.class_count += class_delta
            if prop_delta:
                ir.counts.property_count += prop_delta
            if individual_delta:
                ir.counts.individual_count += individual_delta
            affected = affected_around(ir, store, prefixes, eid)
            refresh_entities(ir, store, prefixes, affected)
            if instance_eid is not None:
                refresh_individual(ir, store, prefixes, instance_eid)
            ix.rebuild_children_of(affected)
            # Inside the lock, after the patch: a saver that already read the
            # generation either sees this bump (its install is vetoed) or ran
            # entirely before the patch — never a half-observed state.
            cache.bump_mutation_gen(oid)
    except Exception:
        # The cached Indexes may carry a partial patch while the file never
        # moved — evict both sides so every read falls back to disk truth,
        # and cancel any pending saver still holding this (maybe half-patched)
        # Store object so the next save starts from the re-parsed clean file.
        cache.drop(oid)
        request.app.state.autosave.cancel(oid)
        raise
    row = (
        OntologyRepository(session).update(
            row.id,
            revision=row.revision + 1,
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            instance_count=ir.counts.individual_count,
        )
        or row
    )
    request.app.state.autosave.schedule(oid, _autosave_saver(request, row, store, prefixes))
    return row


def _autosave_saver(
    request: Request, row: Ontology, store: Store, prefixes: PrefixMap
) -> Callable[[], None]:
    """Build the debounced save closure: serialize, write, refresh row + caches."""
    cache: OntologyCache = request.app.state.cache
    dir_store: LocalUserDirStore = request.app.state.store

    def run() -> None:
        oid = str(row.id)
        ix = _live_indexes(request, row, store, prefixes)
        ir = ix.ir
        gen0 = cache.mutation_gen(oid)
        # serialize stays lock-free: dump() freezes its view at the instant
        # it starts (verified empirically) — edits landing mid-dump enter
        # neither these bytes nor block on them; the edit path never waits.
        data = serialize_store(store, prefixes, row.format)
        if len(data) > MAX_UPLOAD:
            ow_uploads_total.labels("too_large").inc()
            raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
        # Counted just after the dump: ±a few axioms of drift, self-heals next round.
        axiom = _axiom_count(store)
        with cache.file_write_lock(oid):  # exclusive vs PUT /source's file write (seconds, rare)
            dir_store.save(row.owner_user_id, UUID(oid), row.filename, data)
            new_hash = LocalUserDirStore.file_hash(data)
            t0 = time.perf_counter()
            with sessionmaker_or_fail()() as db:
                row2 = (
                    OntologyRepository(db).update(
                        row.id,
                        title=title_of_store(store, row.filename),
                        class_count=ir.counts.class_count,
                        property_count=ir.counts.property_count,
                        axiom_count=axiom,
                        instance_count=ir.counts.individual_count,
                        stats_json={
                            "prefixes": ir.prefixes,
                            "parse_ms": (row.stats_json or {}).get("parse_ms"),
                            "build_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                        },
                        file_size_bytes=len(data),
                        file_hash=new_hash,
                    )
                    or row
                )
        # Phantom guard: everything above ran lock-free, so install only
        # when the generation still matches; an edit that slipped in aborts
        # this install and its own debounced round carries the full state.
        if cache.mutation_gen(oid) == gen0:
            ix_new = build_indexes(ir)  # list()-snapshot iteration tolerates concurrent patches
            write_ir_cache(
                Path(row2.storage_path),
                ir,
                new_hash,
                guard=lambda: cache.mutation_gen(oid) == gen0,  # re-check before the swap
            )
            with cache.mutation_lock(oid):  # µs-scale install window
                if cache.mutation_gen(oid) == gen0:
                    cache.install_indexes(row2, ix_new)
        # Re-key the pool under the landed hash: the next edit reuses this
        # Store (with every pending edit in it) instead of re-parsing.
        cache.refresh_store(row2, store, prefixes)

    return run


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
    """Create a class (with optional parents → subclass); the file lands later."""
    row = _owned_row(user, session, ontology_id)
    _check_revision(body.base_revision, row)
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
        row = _commit_mutation(request, session, row, store, prefixes, iri, class_delta=1)
        return respond(
            {
                "meta": meta_with_state(request, row),
                "entity": _entity_payload(prefixes, iri, "Class"),
            }
        )


@router.post("/ontologies/{ontology_id}/properties")
def create_property(
    ontology_id: str,
    body: PropertyCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Create an object or datatype property; the file lands later."""
    if body.ptype not in ("ObjectProperty", "DatatypeProperty"):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, "ptype must be ObjectProperty or DatatypeProperty"
        )
    row = _owned_row(user, session, ontology_id)
    _check_revision(body.base_revision, row)
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
        row = _commit_mutation(request, session, row, store, prefixes, iri, prop_delta=1)
        return respond(
            {
                "meta": meta_with_state(request, row),
                "entity": _entity_payload(prefixes, iri, "Property"),
            }
        )


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
    _check_revision(body.base_revision, row)
    with _edit_store(request, row) as (store, prefixes):
        ent = _declared(store, eid)
        kind = _kind_of(store, ent)
        touched = body.model_fields_set
        # Validate every IRI ref before the first mutation: a late 422 must
        # leave the pooled Store untouched — the pending autosave serializes
        # this very object, so any half-applied edit would land on disk.
        if body.parents is not None:
            for v in body.parents:
                _iri_or_422(v)
        if body.domains is not None:
            for v in body.domains:
                _iri_or_422(v)
        if body.ranges is not None:
            for v in body.ranges:
                _iri_or_422(v)
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
        row = _commit_mutation(request, session, row, store, prefixes, ent.value)
        return respond(
            {
                "meta": meta_with_state(request, row),
                "entity": _entity_payload(prefixes, ent.value, kind),
            }
        )


@router.delete("/ontologies/{ontology_id}/entities/{eid:path}")
def delete_entity(
    ontology_id: str,
    eid: str,
    baseRevision: int,
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
    _check_revision(baseRevision, row)
    with _edit_store(request, row) as (store, prefixes):
        iri = _declared(store, eid)

        # Count deltas from the type quads themselves, taken before the
        # removal: refresh_entities drops the IR rows, but class/property
        # counts are this side's to keep (a dual-typed IRI counts in both
        # buckets, exactly like the build pass's independent type sets).
        def _typed(t: ox.NamedNode) -> bool:
            return (
                next(store.quads_for_pattern(iri, terms.RDF_TYPE, t, ox.DefaultGraph()), None)
                is not None
            )

        is_class = _typed(terms.OWL_CLASS)
        is_prop = _typed(terms.OWL_OBJECTPROPERTY) or _typed(terms.OWL_DATATYPEPROPERTY)
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
        row = _commit_mutation(
            request,
            session,
            row,
            store,
            prefixes,
            iri.value,
            class_delta=-1 if is_class else 0,
            prop_delta=-1 if is_prop else 0,
        )
        return respond({"removed": removed, "meta": meta_with_state(request, row)})
