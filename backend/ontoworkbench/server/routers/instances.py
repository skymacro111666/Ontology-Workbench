"""Instance editing (B2): create/delete named individuals with assertions.

Rides the exact A2 pipeline from entities.py (spec 2026-08-30 §3): load the
stored file, mutate the Store, revalidate+persist through _persist with the
baseFileHash optimistic lock. Separate module — EntityDialogs' class/property
concerns stay out of instance concerns.
"""

from __future__ import annotations

import pyoxigraph as ox
from fastapi import APIRouter, Depends, Request
from pydantic import Field, field_validator
from pyoxigraph import Store
from sqlalchemy.orm import Session

from ontoworkbench.core import terms
from ontoworkbench.core.parsing import literal_type_ok
from ontoworkbench.db.models import User
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.entities import (
    CamelModel,
    _check_lock,
    _edit_store,
    _entity_payload,
    _iri_for,
    _owned_row,
    _persist,
    _quad,
    _reject_duplicate,
    _remove_all,
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


def _individual(store: Store, eid: str) -> ox.NamedNode:
    """The instance IRI, verified a NamedIndividual, else 404."""
    try:
        iri = ox.NamedNode(eid)
    except ValueError:
        # A non-IRI path can never name an instance (the old URIRef miss).
        raise ApiError(ErrorCode.NOT_FOUND, "No such instance in this ontology") from None
    if (
        next(
            store.quads_for_pattern(
                iri, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL, ox.DefaultGraph()
            ),
            None,
        )
        is None
    ):
        raise ApiError(ErrorCode.NOT_FOUND, "No such instance in this ontology")
    return iri


def _declared_class(store: Store, eid: str) -> ox.NamedNode:
    """A declared class IRI, else 422 (spec §3 validation)."""
    try:
        iri = ox.NamedNode(eid)
    except ValueError:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, f"'{eid}' is not a declared class in this ontology"
        ) from None
    if (
        next(store.quads_for_pattern(iri, terms.RDF_TYPE, terms.OWL_CLASS, ox.DefaultGraph()), None)
        is None
    ):
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


def _prop_of_kind(store: Store, eid: str, kind: str) -> ox.NamedNode:
    """Declared property of the requested kind, else 422 (spec §3)."""
    try:
        iri = ox.NamedNode(eid)
    except ValueError:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR, f"'{eid}' is not a declared {kind} property"
        ) from None
    want = terms.OWL_OBJECTPROPERTY if kind == "object" else terms.OWL_DATATYPEPROPERTY
    if next(store.quads_for_pattern(iri, terms.RDF_TYPE, want, ox.DefaultGraph()), None) is None:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"'{eid}' is not a declared {kind} property")
    return iri


def _replace_assertions(store: Store, iri: ox.NamedNode, rows: list[AssertionInput]) -> None:
    """Drop every declared-property assertion on iri, add the given rows.

    Every row validates before the first mutation: a mid-list failure
    must leave the pooled Store untouched (same doctrine as
    _set_uriref_objects in entities.py).
    """
    plan: list[tuple[ox.NamedNode, ox.NamedNode | ox.Literal]] = []
    for row in rows:
        p = _prop_of_kind(store, row.property, row.kind)
        if row.kind == "object":
            known = False
            try:
                value = ox.NamedNode(row.value)
                known = (
                    next(
                        store.quads_for_pattern(
                            value, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL, ox.DefaultGraph()
                        ),
                        None,
                    )
                    is not None
                )
            except ValueError:
                known = False
            if not known:
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR, f"'{row.value}' is not an existing instance"
                )
            plan.append((p, value))
        else:
            datatype = row.datatype or f"{terms.XSD_NS}string"
            # declared xsd range wins when present
            for q in store.quads_for_pattern(p, terms.RDFS_RANGE, None, ox.DefaultGraph()):
                rng = q.object
                if isinstance(rng, ox.NamedNode) and rng.value.startswith(terms.XSD_NS):
                    datatype = rng.value
                    break
            if not literal_type_ok(row.value, datatype):
                raise ApiError(
                    ErrorCode.VALIDATION_ERROR,
                    f"'{row.value}' is not a valid {datatype.rsplit('#', 1)[-1]}",
                )
            plan.append((p, ox.Literal(row.value, datatype=ox.NamedNode(datatype))))
    props = {
        q.subject.value
        for q in store.quads_for_pattern(
            None, terms.RDF_TYPE, terms.OWL_OBJECTPROPERTY, ox.DefaultGraph()
        )
        if isinstance(q.subject, ox.NamedNode)
    } | {
        q.subject.value
        for q in store.quads_for_pattern(
            None, terms.RDF_TYPE, terms.OWL_DATATYPEPROPERTY, ox.DefaultGraph()
        )
        if isinstance(q.subject, ox.NamedNode)
    }
    for pred in props:
        for q in list(store.quads_for_pattern(iri, ox.NamedNode(pred), None, ox.DefaultGraph())):
            store.remove(q)
    for p, o in plan:
        store.add(_quad(iri, p, o))


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
    with _edit_store(request, row) as (store, prefixes):
        iri = _iri_for(prefixes, body.prefix, body.name)
        _reject_duplicate(store, iri)
        classes = [_declared_class(store, c) for c in body.classes]
        ent = ox.NamedNode(iri)
        store.add(_quad(ent, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL))
        for cls_iri in classes:
            store.add(_quad(ent, terms.RDF_TYPE, cls_iri))
        store.add(_quad(ent, terms.RDFS_LABEL, ox.Literal(body.name)))
        if body.comment:
            store.add(_quad(ent, terms.RDFS_COMMENT, ox.Literal(body.comment)))
        row, _ = _persist(request, session, row, store, prefixes)
        return respond({"meta": meta_of(row), "entity": _entity_payload(prefixes, iri, "Instance")})


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
    with _edit_store(request, row) as (store, prefixes):
        iri = _individual(store, eid)
        removed = 0
        for q in list(store.quads_for_pattern(iri, None, None, ox.DefaultGraph())):
            store.remove(q)
            removed += 1
        object_props = {
            q.subject.value
            for q in store.quads_for_pattern(
                None, terms.RDF_TYPE, terms.OWL_OBJECTPROPERTY, ox.DefaultGraph()
            )
            if isinstance(q.subject, ox.NamedNode)
        }
        for p in object_props:
            for q in list(store.quads_for_pattern(None, ox.NamedNode(p), iri, ox.DefaultGraph())):
                store.remove(q)
                removed += 1
        row, _ = _persist(request, session, row, store, prefixes)
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
    with _edit_store(request, row) as (store, prefixes):
        iri = _individual(store, eid)
        touched = body.model_fields_set
        # null = no-op (only comment clears via null); frontend sends [] to clear
        if "comment" in touched:
            _remove_all(store, iri, terms.RDFS_COMMENT)
            if body.comment:
                store.add(_quad(iri, terms.RDFS_COMMENT, ox.Literal(body.comment)))
        if "classes" in touched and body.classes is not None:
            # Resolve every class before the first removal: a bad name must
            # leave the pooled Store untouched.
            nodes = [_declared_class(store, c) for c in body.classes]
            for q in list(store.quads_for_pattern(iri, terms.RDF_TYPE, None, ox.DefaultGraph())):
                c = q.object
                if (
                    isinstance(c, ox.NamedNode)
                    and next(
                        store.quads_for_pattern(
                            c, terms.RDF_TYPE, terms.OWL_CLASS, ox.DefaultGraph()
                        ),
                        None,
                    )
                    is not None
                ):
                    store.remove(q)
            for cls_iri in nodes:
                store.add(_quad(iri, terms.RDF_TYPE, cls_iri))
        if "assertions" in touched and body.assertions is not None:
            _replace_assertions(store, iri, body.assertions)
        row, _ = _persist(request, session, row, store, prefixes)
        payload = _entity_payload(prefixes, iri.value, "Instance")
        return respond({"meta": meta_of(row), "entity": payload})
