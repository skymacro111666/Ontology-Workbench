"""Instance editing (B2): create/delete named individuals with assertions.

Rides the exact A2 pipeline from entities.py (spec 2026-08-30 §3): load the
stored file, mutate the graph, revalidate+persist through _persist with the
baseFileHash optimistic lock. Separate module — EntityDialogs' class/property
concerns stay out of instance concerns.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from sqlalchemy.orm import Session

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
    graph.add((iri, RDFS.label, Literal(body.name)))
    if body.comment:
        graph.add((iri, RDFS.comment, Literal(body.comment)))
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
