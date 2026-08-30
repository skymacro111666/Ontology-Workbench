"""Instance editing (B2): create/delete named individuals with assertions.

Rides the exact A2 pipeline from entities.py (spec 2026-08-30 §3): load the
stored file, mutate the graph, revalidate+persist through _persist with the
baseFileHash optimistic lock. Separate module — EntityDialogs' class/property
concerns stay out of instance concerns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from rdflib import OWL, RDF, RDFS, Graph, URIRef
from rdflib import Literal as RDFLiteral
from sqlalchemy.orm import Session

from ontoworkbench.core.parsing import literal_type_ok
from ontoworkbench.db.models import User
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.entities import (
    CamelModel,
    _check_lock,
    _entity_payload,
    _iri_for,
    _load_graph,
    _owned_row,
    _persist,
    _reject_duplicate,
)
from ontoworkbench.server.routers.ontologies import meta_of

router = APIRouter(prefix="/api", tags=["instances"])


class InstanceCreate(CamelModel):
    """POST /instances body: minimal shell (assertions join via PUT)."""

    name: str
    prefix: str
    classes: list[str] = Field(default_factory=list)
    comment: str | None = None
    base_file_hash: str


def _individual(graph: Graph, eid: str) -> URIRef:
    """The instance IRI, verified a NamedIndividual, else 404."""
    iri = URIRef(eid)
    if (iri, RDF.type, OWL.NamedIndividual) not in graph:
        raise ApiError(ErrorCode.NOT_FOUND, "No such instance in this ontology")
    return iri


def _declared_class(graph: Graph, eid: str) -> URIRef:
    """A declared class IRI, else 422 (spec §3 validation)."""
    iri = URIRef(eid)
    if (iri, RDF.type, OWL.Class) not in graph:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, f"'{eid}' is not a declared class in this ontology"
        )
    return iri


class AssertionInput(CamelModel):
    """One assertion row (UI 属性行);整体列表随 PUT 全量替换。."""

    property: str
    kind: str  # validated at parse time
    value: str
    datatype: str | None = None

    @field_validator("kind")
    @classmethod
    def validate_kind(cls, v: str) -> str:
        """Validate kind is either 'object' or 'data'."""
        if v not in ("object", "data"):
            raise ValueError("kind must be 'object' or 'data'")
        return v


class InstanceUpdate(CamelModel):
    """PUT /instances body: absent keys stay untouched (A2 semantics)."""

    comment: str | None = None
    classes: list[str] | None = None
    assertions: list[AssertionInput] | None = None
    base_file_hash: str


def _prop_of_kind(graph: Graph, eid: str, kind: str) -> URIRef:
    """Declared property of the requested kind, else 422 (spec §3)."""
    iri = URIRef(eid)
    want = OWL.ObjectProperty if kind == "object" else OWL.DatatypeProperty
    if (iri, RDF.type, want) not in graph:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"'{eid}' is not a declared {kind} property")
    return iri


def _replace_assertions(graph: Graph, iri: URIRef, rows: list[AssertionInput]) -> None:
    """Drop every declared-property assertion on iri, add the given rows."""
    props = set(graph.subjects(RDF.type, OWL.ObjectProperty)) | set(
        graph.subjects(RDF.type, OWL.DatatypeProperty)
    )
    for p in props:
        for t in list(graph.triples((iri, p, None))):
            graph.remove(t)
    for row in rows:
        p = _prop_of_kind(graph, row.property, row.kind)
        if row.kind == "object":
            value = URIRef(row.value)
            if (value, RDF.type, OWL.NamedIndividual) not in graph:
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR, f"'{row.value}' is not an existing instance"
                )
            graph.add((iri, p, value))
        else:
            datatype = row.datatype or "http://www.w3.org/2001/XMLSchema#string"
            # declared xsd range wins when present
            for rng in graph.objects(p, RDFS.range):
                if isinstance(rng, URIRef) and str(rng).startswith(
                    "http://www.w3.org/2001/XMLSchema#"
                ):
                    datatype = str(rng)
                    break
            if not literal_type_ok(row.value, datatype):
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR,
                    f"'{row.value}' is not a valid {datatype.rsplit('#', 1)[-1]}",
                )
            graph.add((iri, p, RDFLiteral(row.value, datatype=URIRef(datatype))))


@router.post("/ontologies/{ontology_id}/instances")
def create_instance(
    ontology_id: str,
    body: InstanceCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Create a named individual with types + auto label (= name)."""
    row = _owned_row(user, session, ontology_id)
    _check_lock(body.base_file_hash, row)
    graph = _load_graph(row)
    iri = _iri_for(graph, body.prefix, body.name)
    _reject_duplicate(graph, iri)
    graph.add((iri, RDF.type, OWL.NamedIndividual))
    for c in body.classes:
        graph.add((iri, RDF.type, _declared_class(graph, c)))
    graph.add((iri, RDFS.label, RDFLiteral(body.name)))
    if body.comment:
        graph.add((iri, RDFS.comment, RDFLiteral(body.comment)))
    row, _ = _persist(request, session, row, graph)
    return respond({"meta": meta_of(row), "entity": _entity_payload(graph, iri, "Instance")})


@router.delete("/ontologies/{ontology_id}/instances/{eid:path}")
def delete_instance(
    ontology_id: str,
    eid: str,
    baseFileHash: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Delete an instance: subject triples + object-property assertions on it.

    Other object references (owl:hasValue axioms etc.) stay — conservative
    prune (spec §3).
    """
    row = _owned_row(user, session, ontology_id)
    _check_lock(baseFileHash, row)
    graph = _load_graph(row)
    iri = _individual(graph, eid)
    removed = 0
    for t in list(graph.triples((iri, None, None))):
        graph.remove(t)
        removed += 1
    object_props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    for p in object_props:
        for t in list(graph.triples((None, p, iri))):
            graph.remove(t)
            removed += 1
    row, _ = _persist(request, session, row, graph)
    return respond({"removed": removed, "meta": meta_of(row)})


@router.put("/ontologies/{ontology_id}/instances/{eid:path}")
def update_instance(
    ontology_id: str,
    eid: str,
    body: InstanceUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Edit comment/classes/assertions; absent keys stay untouched."""
    row = _owned_row(user, session, ontology_id)
    _check_lock(body.base_file_hash, row)
    graph = _load_graph(row)
    iri = _individual(graph, eid)
    touched = body.model_fields_set
    # null = no-op (only comment clears via null); frontend sends [] to clear
    if "comment" in touched:
        graph.remove((iri, RDFS.comment, None))
        if body.comment:
            graph.add((iri, RDFS.comment, RDFLiteral(body.comment)))
    if "classes" in touched and body.classes is not None:
        for c in [o for o in graph.objects(iri, RDF.type) if isinstance(o, URIRef)]:
            if (c, RDF.type, OWL.Class) in graph:
                graph.remove((iri, RDF.type, c))
        for c in body.classes:
            graph.add((iri, RDF.type, _declared_class(graph, c)))
    if "assertions" in touched and body.assertions is not None:
        _replace_assertions(graph, iri, body.assertions)
    row, _ = _persist(request, session, row, graph)
    return respond({"meta": meta_of(row), "entity": _entity_payload(graph, iri, "Instance")})
