"""IR models + assembly from rdflib Graph.

The IR is the stable contract between parsing and all consumers
(API, exporter, future MCP). It is 'page-shaped': one entity carries
everything its detail page needs.
"""

from __future__ import annotations

from collections.abc import Iterable

import rdflib
from pydantic import BaseModel
from rdflib import OWL, RDF, RDFS
from rdflib.term import Literal, Node, URIRef


class Ref(BaseModel):
    """Minimal reference to another entity."""

    eid: str
    curie: str
    label: dict[str, str] = {}


class PropRef(Ref):
    """Reference carrying the property type."""

    ptype: str


class Axiom(BaseModel):
    """Raw axiom serialized as Turtle."""

    turtle: str


class Stats(BaseModel):
    """Aggregate counts for the entity page."""

    direct_children: int = 0
    total_descendants: int = 0


class EntityIR(BaseModel):
    """Everything a detail page renders (spec §5.2)."""

    eid: str
    curie: str
    type: str  # Class | ObjectProperty | DatatypeProperty | Property
    label: dict[str, str] = {}
    comment: str | None = None
    deprecated: bool = False
    parents: list[Ref] = []
    children: list[Ref] = []
    properties: list[PropRef] = []
    referenced_by: list[Ref] = []
    axioms: list[Axiom] = []
    stats: Stats = Stats()


class Counts(BaseModel):
    """Ontology-level counts."""

    class_count: int = 0
    property_count: int = 0
    axiom_count: int = 0


class IRBundle(BaseModel):
    """Full parse result consumed by API/exporter."""

    entities: dict[str, EntityIR]
    counts: Counts
    prefixes: dict[str, str]


def _curie(graph: rdflib.Graph, uri: URIRef) -> str:
    """Compact URI via namespace manager; fall back to full IRI."""
    try:
        prefix, _, local = graph.compute_qname(uri)
        return f"{prefix}:{local}"
    except Exception:  # unbound or split-failing namespaces
        return str(uri)


def _labels(graph: rdflib.Graph, s: URIRef) -> dict[str, str]:
    """All rdfs:label literals keyed by language tag (default 'en')."""
    return {
        str(lit.language or "en"): str(lit)
        for lit in graph.objects(s, RDFS.label)
        if isinstance(lit, Literal)
    }


def _ref(graph: rdflib.Graph, uri: URIRef) -> Ref:
    """Build a Ref for any URIRef in the graph."""
    return Ref(eid=str(uri), curie=_curie(graph, uri), label=_labels(graph, uri))


def _uri_refs(graph: rdflib.Graph, nodes: Iterable[Node]) -> list[Ref]:
    """Map nodes to Refs, keeping only URIRefs (blank nodes dropped)."""
    refs = [_ref(graph, n) for n in nodes if isinstance(n, URIRef)]
    return sorted(refs, key=lambda r: r.curie)


def _ptype_of(graph: rdflib.Graph, uri: URIRef) -> str:
    """ObjectProperty / DatatypeProperty / Property for a property entity."""
    for rdf_type, name in (
        (OWL.ObjectProperty, "ObjectProperty"),
        (OWL.DatatypeProperty, "DatatypeProperty"),
    ):
        if (uri, RDF.type, rdf_type) in graph:
            return name
    return "Property"


def _is_class(graph: rdflib.Graph, uri: Node) -> bool:
    return (uri, RDF.type, OWL.Class) in graph


def _serialize_triples_about(graph: rdflib.Graph, uri: URIRef) -> str:
    """All triples where uri is subject, serialized as Turtle."""
    sub = rdflib.Graph()
    sub.bind("rdfs", RDFS)
    sub.bind("owl", OWL)
    for prefix, ns in graph.namespaces():
        if prefix:
            sub.bind(prefix, ns)
    for triple in graph.triples((uri, None, None)):
        sub.add(triple)
    return sub.serialize(format="turtle").strip()


def build_ir(graph: rdflib.Graph) -> IRBundle:
    """Walk the graph once and assemble page-shaped entities."""
    classes = sorted(
        (s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)),
        key=str,
    )
    object_props = set(graph.subjects(RDF.type, OWL.ObjectProperty))
    datatype_props = set(graph.subjects(RDF.type, OWL.DatatypeProperty))
    props = sorted(
        (s for s in (object_props | datatype_props) if isinstance(s, URIRef)),
        key=str,
    )

    entities: dict[str, EntityIR] = {}
    for uri in [*classes, *props]:
        is_class = _is_class(graph, uri)
        etype = "Class" if is_class else _ptype_of(graph, uri)

        parents = _uri_refs(graph, graph.objects(uri, RDFS.subClassOf))
        children = _uri_refs(graph, graph.subjects(RDFS.subClassOf, uri)) if is_class else []

        properties: list[PropRef] = []
        if is_class:
            for p in props:
                linked = set(graph.objects(p, RDFS.domain)) | set(graph.objects(p, RDFS.range))
                if uri in linked:
                    base = _ref(graph, p)
                    properties.append(
                        PropRef(
                            eid=base.eid,
                            curie=base.curie,
                            label=base.label,
                            ptype=_ptype_of(graph, p),
                        )
                    )

        if is_class:
            referenced = _uri_refs(graph, graph.subjects(RDFS.subClassOf, uri))
        else:
            referenced = _uri_refs(
                graph,
                (*graph.subjects(RDFS.domain, uri), *graph.subjects(RDFS.range, uri)),
            )

        comment = next(
            (str(c) for c in graph.objects(uri, RDFS.comment) if isinstance(c, Literal)),
            None,
        )
        entities[str(uri)] = EntityIR(
            eid=str(uri),
            curie=_curie(graph, uri),
            type=etype,
            label=_labels(graph, uri),
            comment=comment,
            deprecated=bool((uri, OWL.deprecated, Literal(True)) in graph),
            parents=parents,
            children=children,
            properties=properties,
            referenced_by=sorted({r.eid: r for r in referenced}.values(), key=lambda r: r.curie),
            axioms=[Axiom(turtle=_serialize_triples_about(graph, uri))],
            stats=Stats(direct_children=len(children)),
        )

    counts = Counts(
        class_count=len(classes),
        property_count=len(props),
        axiom_count=len(graph),
    )
    prefixes = {p or "base": str(n) for p, n in graph.namespaces()}
    return IRBundle(entities=entities, counts=counts, prefixes=prefixes)
