"""IR models + assembly from rdflib Graph.

The IR is the stable contract between parsing and all consumers
(API, exporter, future MCP). It is 'page-shaped': one entity carries
everything its detail page needs.
"""

from __future__ import annotations

import re
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
    """Reference carrying the property type and its domain/range classes."""

    ptype: str
    domain: list[Ref] = []
    range: list[Ref] = []


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
    kind: str = "entity"


class ObjectAssertion(BaseModel):
    """实例 → 另一实例(谓词为已声明 ObjectProperty)."""

    property: PropRef
    object: Ref


class DataAssertion(BaseModel):
    """实例 → 类型字面量(谓词为已声明 DatatypeProperty,无语言标签)."""

    property: PropRef
    value: str
    datatype: str


class IndividualIR(BaseModel):
    """实例详情页载荷(spec 2026-08-30 §2)."""

    eid: str
    curie: str
    kind: str = "instance"
    label: dict[str, str] = {}
    comment: str | None = None
    classes: list[Ref] = []
    object_assertions: list[ObjectAssertion] = []
    data_assertions: list[DataAssertion] = []


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
    # The owl:Ontology subject IRI (provenance for exports); None when the
    # file never declares one.
    ontology_iri: str | None = None
    # class eid → its direct named individuals (on-demand canvas data,
    # deliberately outside entities so schema walks/counts stay unchanged)
    instances: dict[str, list[Ref]] = {}
    individuals: dict[str, IndividualIR] = {}


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


XSD_STRING = "http://www.w3.org/2001/XMLSchema#string"


def _prop_ref(graph: rdflib.Graph, uri: URIRef) -> PropRef:
    """PropRef for a declared property URI, with its domain/range classes."""
    return PropRef(
        **_ref(graph, uri).model_dump(),
        ptype=_ptype_of(graph, uri),
        domain=_uri_refs(graph, graph.objects(uri, RDFS.domain)),
        range=_uri_refs(graph, graph.objects(uri, RDFS.range)),
    )


def _is_class(graph: rdflib.Graph, uri: Node) -> bool:
    return (uri, RDF.type, OWL.Class) in graph


_TTL_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# Conservative PN_LOCAL whitelist; anything else renders as <iri> (always valid).
_PN_LOCAL = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_\-.]*[A-Za-z0-9_\-])?\Z")


def _ttl_literal(lit: Literal) -> str:
    """One rdflib Literal as a Turtle quoted string with tag/datatype."""
    text = "".join(_TTL_ESCAPES.get(ch, ch) for ch in str(lit))
    if lit.language:
        return f'"{text}"@{lit.language}'
    if lit.datatype is not None:
        return f'"{text}"^^<{lit.datatype}>'
    return f'"{text}"'


def _ttl_term(
    graph: rdflib.Graph,
    term: Node,
    bindings: dict[str, str] | None = None,
    bnodes: dict[Node, str] | None = None,
) -> str:
    """One RDF term as Turtle: prefixed name, <iri>, literal or bnode.

    Prefixed renderings record their namespace in `bindings` (when given)
    so the caller can emit a self-contained block with @prefix lines; a
    `bnodes` map relabels blank nodes to _:b0, _:b1… by first appearance
    (raw ids are random per parse, which would break rebuild determinism).
    """
    if isinstance(term, URIRef):
        try:
            prefix, namespace, local = graph.compute_qname(term)
        except Exception:  # unbound or split-failing namespace
            return f"<{term}>"
        if prefix and _PN_LOCAL.match(local):
            if bindings is not None:
                bindings[prefix] = str(namespace)
            return f"{prefix}:{local}"
        return f"<{term}>"
    if isinstance(term, Literal):
        return _ttl_literal(term)
    if bnodes is None:
        return term.n3()
    label = bnodes.get(term)
    if label is None:
        label = bnodes[term] = f"_:b{len(bnodes)}"
    return label


def _turtle_block(graph: rdflib.Graph, uri: URIRef) -> str:
    """All triples with uri as subject, one self-contained Turtle block.

    Replaces the per-entity rdflib sub-graph + turtle serializer (a full
    prefix computation and sort per entity — the dominant build_ir cost on
    50k-class ontologies). Same triple set, hand-grouped by predicate, with
    the used @prefix declarations leading the block like the old output.
    """
    by_pred: dict[str, tuple[Node, list[Node]]] = {}
    for _, p, o in graph.triples((uri, None, None)):
        entry = by_pred.get(str(p))
        if entry is None:
            by_pred[str(p)] = (p, [o])
        else:
            entry[1].append(o)
    if not by_pred:
        return ""
    bindings: dict[str, str] = {}
    bnodes: dict[Node, str] = {}
    parts: list[str] = []
    for key in sorted(by_pred):
        p, objs = by_pred[key]
        pred = "a" if p == RDF.type else _ttl_term(graph, p, bindings, bnodes)
        rendered = sorted(_ttl_term(graph, o, bindings, bnodes) for o in objs)
        parts.append(f"{pred} " + " , ".join(rendered))
    subject = _ttl_term(graph, uri, bindings, bnodes)
    text = f"{subject} {parts[0]}"
    for part in parts[1:]:
        text += f" ;\n    {part}"
    text += " ."
    header = "".join(
        f"@prefix {prefix}: <{namespace}> .\n" for prefix, namespace in sorted(bindings.items())
    )
    return f"{header}\n{text}" if header else text


def build_ir(graph: rdflib.Graph) -> IRBundle:
    """Walk the graph once and assemble page-shaped entities."""
    classes = sorted(
        (s for s in graph.subjects(RDF.type, OWL.Class) if isinstance(s, URIRef)),
        key=str,
    )
    object_props: set[URIRef] = set()
    datatype_props: set[URIRef] = set()
    for s in graph.subjects(RDF.type, OWL.ObjectProperty):
        if isinstance(s, URIRef):
            object_props.add(s)
    for s in graph.subjects(RDF.type, OWL.DatatypeProperty):
        if isinstance(s, URIRef):
            datatype_props.add(s)
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
                properties.append(_prop_ref(graph, p))

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
            axioms=[Axiom(turtle=_turtle_block(graph, uri))],
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
    individuals_out: dict[str, IndividualIR] = {}
    individuals: set[str] = set()
    for ind in sorted(
        (s for s in graph.subjects(RDF.type, OWL.NamedIndividual) if isinstance(s, URIRef)),
        key=str,
    ):
        individuals.add(str(ind))
        comment = next(
            (str(c) for c in graph.objects(ind, RDFS.comment) if isinstance(c, Literal)),
            None,
        )
        cls: list[Ref] = []
        obj_asserts: list[ObjectAssertion] = []
        data_asserts: list[DataAssertion] = []
        for pred, obj in graph.predicate_objects(ind):
            if pred == RDF.type:
                if obj in class_set and isinstance(obj, URIRef):
                    instances.setdefault(str(obj), []).append(_ref(graph, ind))
                    cls.append(_ref(graph, obj))
            elif isinstance(pred, URIRef) and pred in object_props and isinstance(obj, URIRef):
                obj_asserts.append(
                    ObjectAssertion(property=_prop_ref(graph, pred), object=_ref(graph, obj))
                )
            elif (
                isinstance(pred, URIRef)
                and pred in datatype_props
                and isinstance(obj, Literal)
                and obj.datatype is not None
            ):
                data_asserts.append(
                    DataAssertion(
                        property=_prop_ref(graph, pred), value=str(obj), datatype=str(obj.datatype)
                    )
                )
        individuals_out[str(ind)] = IndividualIR(
            eid=str(ind),
            curie=_curie(graph, ind),
            label=_labels(graph, ind),
            comment=comment,
            classes=sorted(cls, key=lambda r: r.curie),
            object_assertions=sorted(obj_asserts, key=lambda a: a.property.curie),
            data_assertions=sorted(data_asserts, key=lambda a: a.property.curie),
        )

    counts.individual_count = len(individuals)

    # owl:Ontology subject IRI, deterministic under multiple declarations.
    onto_subjects = sorted(
        (str(s) for s in graph.subjects(RDF.type, OWL.Ontology) if isinstance(s, URIRef)),
    )
    return IRBundle(
        entities=entities,
        counts=counts,
        prefixes=prefixes,
        ontology_iri=onto_subjects[0] if onto_subjects else None,
        instances=instances,
        individuals=individuals_out,
    )
