"""Graph-side entity editing (A2): create classes/properties, edit, delete.

Each write mutates an rdflib graph loaded from the stored file, then walks
the A1 persistence pipeline (serialize → reparse → atomic write → row/cache
refresh). Optimistic lock via baseFileHash on every mutation, exactly like
PUT /source (design spec 2026-08-26 §4).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.term import Node
from sqlalchemy.orm import Session

from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.parsing import serialize_graph, timed_parse
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.observability.metrics import ow_parse_seconds, ow_uploads_total
from ontoworkbench.server.cache import OntologyCache
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.ontologies import (
    MAX_UPLOAD,
    meta_of,
    title_of,
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


def _load_graph(row: Ontology) -> Graph:
    """Parse the stored file back into a mutable graph."""
    return Graph().parse(data=Path(row.storage_path).read_bytes(), format=_rdf_format(row.format))


def _rdf_format(fmt: str) -> str:
    """Internal format name → rdflib serializer name."""
    return {"turtle": "turtle", "rdfxml": "xml", "jsonld": "json-ld"}[fmt]


def _iri_for(graph: Graph, prefix: str, name: str) -> URIRef:
    """Mint prefix:name; unknown prefix or bad name is a 422."""
    if not _NAME_RE.match(name):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid name '{name}'",
            "Use a letter/underscore start, then letters, digits, ., - or _.",
        )
    for p, ns in graph.namespaces():
        if p == prefix:
            return URIRef(str(ns) + name)
    known = ", ".join(sorted({p for p, _ in graph.namespaces() if p})) or "(none)"
    raise _unknown_prefix(prefix, known) from None


def _unknown_prefix(prefix: str, known: str) -> ApiError:
    """Build the unknown-prefix 422 with the usable-prefix hint."""
    return ApiError(
        ErrorCode.VALIDATION_ERROR,
        f"Unknown prefix '{prefix}'",
        f"Known prefixes: {known}",
    )


def _reject_duplicate(graph: Graph, iri: URIRef) -> None:
    """Refuse to mint an IRI that already carries triples."""
    if any(graph.triples((iri, None, None))) or any(graph.triples((None, None, iri))):
        raise ApiError(
            ErrorCode.DUPLICATE_ENTITY,
            f"'{iri}' is already used in this ontology",
            "Pick a different name or prefix.",
        )


def _set_label(graph: Graph, ent: URIRef, label: LabelInput | None) -> None:
    """Replace all rdfs:label values with the one given (None clears)."""
    graph.remove((ent, RDFS.label, None))
    if label and label.value:
        graph.add(
            (
                ent,
                RDFS.label,
                Literal(label.value, lang=label.lang) if label.lang else Literal(label.value),
            )
        )


def _set_comment(graph: Graph, ent: URIRef, comment: str | None) -> None:
    """Replace all rdfs:comment values (None clears)."""
    graph.remove((ent, RDFS.comment, None))
    if comment:
        graph.add((ent, RDFS.comment, Literal(comment)))


def _set_uriref_objects(graph: Graph, ent: URIRef, pred: URIRef, values: list[str] | None) -> None:
    """Replace pred objects, keeping blank-node axioms (owl:Restriction etc.).

    Only URIRef objects are removed: rdfs:subClassOf restrictions live in
    blank nodes and must survive reparenting untouched.
    """
    for o in [o for o in graph.objects(ent, pred) if isinstance(o, URIRef)]:
        graph.remove((ent, pred, o))
    for v in values or []:
        graph.add((ent, pred, URIRef(v)))


def _entity_payload(graph: Graph, iri: URIRef, kind: str) -> dict[str, Any]:
    """Small entity reference for write responses (full data via GET)."""
    try:
        curie = graph.compute_qname(iri)[2]
        prefix = graph.compute_qname(iri)[0]
        curie = f"{prefix}:{curie}"
    except Exception:
        curie = str(iri)
    return {"eid": str(iri), "curie": curie, "type": kind}


def _persist(
    request: Request, session: Session, row: Ontology, graph: Graph
) -> tuple[Ontology, Any]:
    """Serialize → revalidate → atomic write → row/cache refresh (A1 shape)."""
    data = serialize_graph(graph, row.format)
    if len(data) > MAX_UPLOAD:
        ow_uploads_total.labels("too_large").inc()
        raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
    with ow_parse_seconds.labels(row.format).time():
        check, parse_ms = timed_parse(data, row.format)
    ir = build_ir(check)

    store: LocalUserDirStore = request.app.state.store
    store.save(row.owner_user_id, UUID(str(row.id)), row.filename, data)
    repos = OntologyRepository(session)
    row = (
        repos.update(
            row.id,
            title=title_of(graph, row.filename),
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            axiom_count=ir.counts.axiom_count,
            instance_count=ir.counts.individual_count,
            stats_json={"prefixes": ir.prefixes, "parse_ms": round(parse_ms, 1)},
            file_size_bytes=len(data),
            file_hash=LocalUserDirStore.file_hash(data),
        )
        or row
    )
    cache: OntologyCache = request.app.state.cache
    cache.indexes_for(row, lambda r: build_indexes(ir))
    return row, ir


def _declared(graph: Graph, eid: str) -> URIRef:
    """The entity IRI, verified declared (typed) in the graph, else 404."""
    iri = URIRef(eid)
    if not any(graph.triples((iri, RDF.type, None))):
        raise ApiError(ErrorCode.NOT_FOUND, "No such entity in this ontology")
    return iri


def _kind_of(graph: Graph, iri: URIRef) -> str:
    """Class or property (for the response payload)."""
    if (iri, RDF.type, OWL.Class) in graph:
        return "Class"
    return "Property"


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
    graph = _load_graph(row)
    iri = _iri_for(graph, body.prefix, body.name)
    _reject_duplicate(graph, iri)
    graph.add((iri, RDF.type, OWL.Class))
    _set_label(graph, iri, body.label)
    _set_comment(graph, iri, body.comment)
    for parent in body.parents:
        graph.add((iri, RDFS.subClassOf, URIRef(parent)))
    row, _ = _persist(request, session, row, graph)
    return respond({"meta": meta_of(row), "entity": _entity_payload(graph, iri, "Class")})


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
    graph = _load_graph(row)
    iri = _iri_for(graph, body.prefix, body.name)
    _reject_duplicate(graph, iri)
    graph.add(
        (
            iri,
            RDF.type,
            OWL.ObjectProperty if body.ptype == "ObjectProperty" else OWL.DatatypeProperty,
        )
    )
    _set_label(graph, iri, body.label)
    _set_comment(graph, iri, body.comment)
    for d in body.domains:
        graph.add((iri, RDFS.domain, URIRef(d)))
    for r in body.ranges:
        graph.add((iri, RDFS.range, URIRef(r)))
    row, _ = _persist(request, session, row, graph)
    return respond({"meta": meta_of(row), "entity": _entity_payload(graph, iri, "Property")})


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
    graph = _load_graph(row)
    iri = _declared(graph, eid)
    kind = _kind_of(graph, iri)
    touched = body.model_fields_set
    if "label" in touched:
        _set_label(graph, iri, body.label)
    if "comment" in touched:
        _set_comment(graph, iri, body.comment)
    if "parents" in touched and body.parents is not None:
        _set_uriref_objects(graph, iri, RDFS.subClassOf, body.parents)
    if "domains" in touched and body.domains is not None:
        _set_uriref_objects(graph, iri, RDFS.domain, body.domains)
    if "ranges" in touched and body.ranges is not None:
        _set_uriref_objects(graph, iri, RDFS.range, body.ranges)
    row, _ = _persist(request, session, row, graph)
    return respond({"meta": meta_of(row), "entity": _entity_payload(graph, iri, kind)})


@router.delete("/ontologies/{ontology_id}/entities/{eid:path}")
def delete_entity(
    ontology_id: str,
    eid: str,
    baseFileHash: str,
    request: Request,
    prune: bool = True,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Delete an entity's triples; prune also drops reverse references.

    Pruned: subclasses' subClassOf → it, properties' domain/range → it,
    instances' rdf:type → it (they lose the type and leave the canvas).
    """
    row = _owned_row(user, session, ontology_id)
    _check_lock(baseFileHash, row)
    graph = _load_graph(row)
    iri = _declared(graph, eid)
    removed = 0
    for t in list(graph.triples((iri, None, None))):
        graph.remove(t)
        removed += 1
    if prune:
        reverse: list[tuple[Node, URIRef, Node]] = [
            (s, p, iri)
            for p in (RDFS.subClassOf, RDFS.domain, RDFS.range, RDF.type)
            for s in graph.subjects(p, iri)
        ]
        for t in reverse:
            graph.remove(t)
            removed += 1
    row, _ = _persist(request, session, row, graph)
    return respond({"removed": removed, "meta": meta_of(row)})
