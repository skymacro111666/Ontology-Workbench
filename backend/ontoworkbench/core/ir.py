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


class CounterpartRef(Ref):
    """An axiom's far end, flagged for the UI.

    Declared entities have a detail page to navigate to; external IRIs
    (xsd datatypes, foreign vocabulary) render as plain text.
    """

    declared: bool = False


class ReferencedRef(Ref):
    """Reverse reference carrying the axiom relating the two entities.

    counterpart is the axiom's other end (the range class for a domain
    ref, the domain class for a range ref); None when untyped.
    """

    relation: str = ""
    counterpart: CounterpartRef | None = None


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
    referenced_by: list[ReferencedRef] = []
    axioms: list[Axiom] = []
    stats: Stats = Stats()


class Counts(BaseModel):
    """Ontology-level counts."""

    class_count: int = 0
    property_count: int = 0
    axiom_count: int = 0
    individual_count: int = 0


class IRBundle(BaseModel):
    """Full parse result consumed by API/exporter."""

    entities: dict[str, EntityIR]
    counts: Counts
    prefixes: dict[str, str]
    # class eid → its direct named individuals (on-demand canvas data,
    # deliberately outside entities so schema walks/counts stay unchanged)
    instances: dict[str, list[Ref]] = {}


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

    # Domain/range links walked once: props by class and classes by prop.
    props_by_class: dict[URIRef, list[URIRef]] = {}
    classes_by_prop: dict[URIRef, list[tuple[URIRef, str]]] = {}
    for p in props:
        for link, relation in ((RDFS.domain, "rdfs:domain"), (RDFS.range, "rdfs:range")):
            for c in graph.objects(p, link):
                if isinstance(c, URIRef):
                    props_by_class.setdefault(c, []).append(p)
                    classes_by_prop.setdefault(p, []).append((c, relation))

    # Declared entities (own classes and properties): the far ends the UI
    # may link into; everything else is external vocabulary.
    declared_uris = set(classes) | set(props)

    def _referenced(uri: URIRef, is_class: bool, children: list[Ref]) -> list[ReferencedRef]:
        """Entities whose axioms mention uri: subclassers and domain/range peers."""

        def _counterpart(prop: URIRef, relation: str) -> CounterpartRef | None:
            """The axiom's far end: range of prop for a domain ref, vice versa."""
            other = RDFS.range if relation == "rdfs:domain" else RDFS.domain
            far = next((o for o in graph.objects(prop, other) if isinstance(o, URIRef)), None)
            if far is None:
                return None
            return CounterpartRef(**_ref(graph, far).model_dump(), declared=far in declared_uris)

        refs = {
            r.eid: ReferencedRef(eid=r.eid, curie=r.curie, label=r.label, relation="subClassOf")
            for r in children
        }
        if is_class:
            for p in props_by_class.get(uri, []):
                base = _ref(graph, p)
                relation = "rdfs:domain" if uri in graph.objects(p, RDFS.domain) else "rdfs:range"
                refs[base.eid] = ReferencedRef(
                    eid=base.eid,
                    curie=base.curie,
                    label=base.label,
                    relation=relation,
                    counterpart=_counterpart(p, relation),
                )
        else:
            for c, relation in classes_by_prop.get(uri, []):
                base = _ref(graph, c)
                refs[base.eid] = ReferencedRef(
                    eid=base.eid,
                    curie=base.curie,
                    label=base.label,
                    relation=relation,
                    counterpart=_counterpart(uri, relation),
                )
        return sorted(refs.values(), key=lambda r: r.curie)

    for uri in [*classes, *props]:
        is_class = _is_class(graph, uri)
        etype = "Class" if is_class else _ptype_of(graph, uri)

        parents = _uri_refs(graph, graph.objects(uri, RDFS.subClassOf))
        children = _uri_refs(graph, graph.subjects(RDFS.subClassOf, uri)) if is_class else []

        properties: list[PropRef] = []
        if is_class:
            for p in props_by_class.get(uri, []):
                base = _ref(graph, p)
                properties.append(
                    PropRef(
                        eid=base.eid,
                        curie=base.curie,
                        label=base.label,
                        ptype=_ptype_of(graph, p),
                    )
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
            referenced_by=_referenced(uri, is_class, children),
            axioms=[Axiom(turtle=_serialize_triples_about(graph, uri))],
            stats=Stats(direct_children=len(children)),
        )

    # Total descendants per class (memoized DFS over the assembled children).
    child_eids: dict[str, list[str]] = {}
    for e in entities.values():
        for child in e.children:
            child_eids.setdefault(e.eid, []).append(child.eid)
    descendants: dict[str, int] = {}

    def _total_descendants(eid: str) -> int:
        if eid not in descendants:
            descendants[eid] = 0  # cycle guard
            descendants[eid] = sum(1 + _total_descendants(c) for c in child_eids.get(eid, []))
        return descendants[eid]

    for e in entities.values():
        e.stats = Stats(
            direct_children=e.stats.direct_children,
            total_descendants=_total_descendants(e.eid),
        )

    counts = Counts(
        class_count=len(classes),
        property_count=len(props),
        axiom_count=len(graph),
    )
    # Only namespaces the graph actually uses; rdflib seeds ~29 built-ins.
    used_iris = {str(t) for triple in graph for t in triple if isinstance(t, URIRef)}
    prefixes = {
        p or "base": str(n)
        for p, n in graph.namespaces()
        if any(iri.startswith(str(n)) for iri in used_iris)
    }

    # Named individuals group under their declared rdf:type classes (direct
    # typing only — no subclass inference, matching the badge's direct count).
    class_set = set(classes)
    instances: dict[str, list[Ref]] = {}
    individuals: set[str] = set()
    for ind in sorted(
        (s for s in graph.subjects(RDF.type, OWL.NamedIndividual) if isinstance(s, URIRef)),
        key=str,
    ):
        individuals.add(str(ind))
        for t in graph.objects(ind, RDF.type):
            if t in class_set:
                instances.setdefault(str(t), []).append(_ref(graph, ind))

    counts.individual_count = len(individuals)
    return IRBundle(entities=entities, counts=counts, prefixes=prefixes, instances=instances)
