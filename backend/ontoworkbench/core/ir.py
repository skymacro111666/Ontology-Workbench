"""IR models + assembly from rdflib Graph or pyoxigraph Store.

The IR is the stable contract between parsing and all consumers
(API, exporter, future MCP). It is 'page-shaped': one entity carries
everything its detail page needs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

import pyoxigraph as ox
import rdflib
from pydantic import BaseModel
from rdflib import OWL, RDF, RDFS
from rdflib.term import Literal, Node, URIRef

from ontoworkbench.core import terms
from ontoworkbench.core.prefixes import PrefixMap


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


_QName = tuple[str, str, str]
_QNameCache = dict[URIRef, _QName | None]


def _qname(graph: rdflib.Graph, uri: URIRef, cache: _QNameCache | None = None) -> _QName | None:
    """compute_qname with an optional per-build memo (None = unresolvable).

    The same URI is qname-resolved many times per build (entity curie,
    refs, axiom blocks); one memo across the whole build_ir walk keeps
    compute_qname's namespace search to once per distinct URI.
    """
    if cache is not None and uri in cache:
        return cache[uri]
    try:
        prefix, namespace, local = graph.compute_qname(uri)
        qname = (prefix, str(namespace), local)
    except Exception:  # unbound or split-failing namespaces
        qname = None
    if cache is not None:
        cache[uri] = qname
    return qname


def _curie(graph: rdflib.Graph, uri: URIRef, cache: _QNameCache | None = None) -> str:
    """Compact URI via namespace manager; fall back to full IRI."""
    qname = _qname(graph, uri, cache)
    return f"{qname[0]}:{qname[2]}" if qname else str(uri)


def _labels(graph: rdflib.Graph, s: URIRef) -> dict[str, str]:
    """All rdfs:label literals keyed by language tag (default 'en')."""
    return {
        str(lit.language or "en"): str(lit)
        for lit in graph.objects(s, RDFS.label)
        if isinstance(lit, Literal)
    }


def _ref(graph: rdflib.Graph, uri: URIRef, cache: _QNameCache | None = None) -> Ref:
    """Build a Ref for any URIRef in the graph."""
    return Ref(eid=str(uri), curie=_curie(graph, uri, cache), label=_labels(graph, uri))


def _uri_refs(
    graph: rdflib.Graph, nodes: Iterable[Node], cache: _QNameCache | None = None
) -> list[Ref]:
    """Map nodes to Refs, keeping only URIRefs (blank nodes dropped)."""
    refs = [_ref(graph, n, cache) for n in nodes if isinstance(n, URIRef)]
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


def _prop_ref(graph: rdflib.Graph, uri: URIRef, cache: _QNameCache | None = None) -> PropRef:
    """PropRef for a declared property URI, with its domain/range classes."""
    return PropRef(
        **_ref(graph, uri, cache).model_dump(),
        ptype=_ptype_of(graph, uri),
        domain=_uri_refs(graph, graph.objects(uri, RDFS.domain), cache),
        range=_uri_refs(graph, graph.objects(uri, RDFS.range), cache),
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
    cache: _QNameCache | None = None,
) -> str:
    """One RDF term as Turtle: prefixed name, <iri>, literal or bnode.

    Prefixed renderings record their namespace in `bindings` (when given)
    so the caller can emit a self-contained block with @prefix lines; a
    `bnodes` map relabels blank nodes to _:b0, _:b1… by first appearance
    (raw ids are random per parse, which would break rebuild determinism).
    """
    if isinstance(term, URIRef):
        qname = _qname(graph, term, cache)
        if qname is not None and qname[0] and _PN_LOCAL.match(qname[2]):
            if bindings is not None:
                bindings[qname[0]] = qname[1]
            return f"{qname[0]}:{qname[2]}"
        return f"<{term}>"
    if isinstance(term, Literal):
        return _ttl_literal(term)
    if bnodes is None:
        return term.n3()
    label = bnodes.get(term)
    if label is None:
        label = bnodes[term] = f"_:b{len(bnodes)}"
    return label


def _turtle_block(graph: rdflib.Graph, uri: URIRef, cache: _QNameCache | None = None) -> str:
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
        pred = "a" if p == RDF.type else _ttl_term(graph, p, bindings, bnodes, cache)
        rendered = sorted(_ttl_term(graph, o, bindings, bnodes, cache) for o in objs)
        parts.append(f"{pred} " + " , ".join(rendered))
    subject = _ttl_term(graph, uri, bindings, bnodes, cache)
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
    # One qname memo for the whole walk: entity curies, refs and axiom
    # blocks re-resolve the same URIs constantly.
    cc: _QNameCache = {}

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
            return CounterpartRef(
                **_ref(graph, far, cc).model_dump(), declared=far in declared_uris
            )

        refs = {
            r.eid: ReferencedRef(eid=r.eid, curie=r.curie, label=r.label, relation="subClassOf")
            for r in children
        }
        if is_class:
            for p in props_by_class.get(uri, []):
                base = _ref(graph, p, cc)
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
                base = _ref(graph, c, cc)
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

        parents = _uri_refs(graph, graph.objects(uri, RDFS.subClassOf), cc)
        children = _uri_refs(graph, graph.subjects(RDFS.subClassOf, uri), cc) if is_class else []

        properties: list[PropRef] = []
        if is_class:
            for p in props_by_class.get(uri, []):
                properties.append(_prop_ref(graph, p, cc))

        comment = next(
            (str(c) for c in graph.objects(uri, RDFS.comment) if isinstance(c, Literal)),
            None,
        )
        entities[str(uri)] = EntityIR(
            eid=str(uri),
            curie=_curie(graph, uri, cc),
            type=etype,
            label=_labels(graph, uri),
            comment=comment,
            deprecated=bool((uri, OWL.deprecated, Literal(True)) in graph),
            parents=parents,
            children=children,
            properties=properties,
            referenced_by=_referenced(uri, is_class, children),
            axioms=[Axiom(turtle=_turtle_block(graph, uri, cc))],
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
    # One explicit pass (no per-term generator frames) over 1.4M+ triples.
    used_iris: set[str] = set()
    _add_used = used_iris.add
    for subj, pred, obj in graph:
        if type(subj) is URIRef:
            _add_used(str(subj))
        if type(pred) is URIRef:
            _add_used(str(pred))
        if type(obj) is URIRef:
            _add_used(str(obj))
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
                    instances.setdefault(str(obj), []).append(_ref(graph, ind, cc))
                    cls.append(_ref(graph, obj, cc))
            elif isinstance(pred, URIRef) and pred in object_props and isinstance(obj, URIRef):
                obj_asserts.append(
                    ObjectAssertion(
                        property=_prop_ref(graph, pred, cc), object=_ref(graph, obj, cc)
                    )
                )
            elif (
                isinstance(pred, URIRef)
                and pred in datatype_props
                and isinstance(obj, Literal)
                and obj.datatype is not None
            ):
                data_asserts.append(
                    DataAssertion(
                        property=_prop_ref(graph, pred, cc),
                        value=str(obj),
                        datatype=str(obj.datatype),
                    )
                )
        individuals_out[str(ind)] = IndividualIR(
            eid=str(ind),
            curie=_curie(graph, ind, cc),
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


# ---------------------------------------------------------------------------
# pyoxigraph path. build_ir_store + the _ox_* helpers below mirror the rdflib
# build_ir above; the two must stay in lockstep until the callers move and the
# rdflib side is deleted. IR semantics are triple/default-graph: every
# traversal pins ox.DefaultGraph() (bare Store iteration would leak
# named-graph quads), and axiom_count is a SPARQL COUNT over the default
# graph rather than len(store) for the same reason.

_OxTerm = ox.NamedNode | ox.BlankNode | ox.Literal | ox.Triple
# Memo for the whole build_ir_store walk: uri -> (prefix, local) | None.
# curie_for scans the prefix table per call; one memo bounds it to once per
# distinct URI (~100k on go.owl) instead of once per rendered term (~1.5M).
_OxCurieCache = dict[str, tuple[str, str] | None]
# RDF 1.1 boolean canonical form; matches turtle's bare `true` token.
_OX_TRUE = ox.Literal("true", datatype=terms.XSD_BOOLEAN)


def _ox_curie_for(
    prefixes: PrefixMap, uri: str, cache: _OxCurieCache | None = None
) -> tuple[str, str] | None:
    """PrefixMap.curie_for with an optional per-build memo (None = unresolvable)."""
    if cache is not None and uri in cache:
        return cache[uri]
    curie = prefixes.curie_for(uri)
    if cache is not None:
        cache[uri] = curie
    return curie


def _ox_curie(prefixes: PrefixMap, uri: str, cache: _OxCurieCache | None = None) -> str:
    """Compact URI via the prefix map; fall back to the full IRI."""
    curie = _ox_curie_for(prefixes, uri, cache)
    return f"{curie[0]}:{curie[1]}" if curie else uri


def _ox_subjects(store: ox.Store, p: ox.NamedNode, o: ox.NamedNode) -> Iterator[_OxTerm]:
    """Subjects of (p, o) in the default graph."""
    for q in store.quads_for_pattern(None, p, o, ox.DefaultGraph()):
        yield q.subject


def _ox_objects(store: ox.Store, s: str, p: ox.NamedNode) -> Iterator[_OxTerm]:
    """Objects of (s, p) in the default graph."""
    for q in store.quads_for_pattern(ox.NamedNode(s), p, None, ox.DefaultGraph()):
        yield q.object


def _ox_has(store: ox.Store, s: str, p: ox.NamedNode, o: ox.NamedNode | ox.Literal) -> bool:
    """Whether (s, p, o) is present in the default graph."""
    return next(store.quads_for_pattern(ox.NamedNode(s), p, o, ox.DefaultGraph()), None) is not None


def _ox_labels(store: ox.Store, s: str) -> dict[str, str]:
    """All rdfs:label literals keyed by language tag (default 'en')."""
    out: dict[str, str] = {}
    for q in store.quads_for_pattern(ox.NamedNode(s), terms.RDFS_LABEL, None, ox.DefaultGraph()):
        obj = q.object
        if isinstance(obj, ox.Literal):
            out[obj.language or "en"] = obj.value
    return out


def _ox_ref(
    store: ox.Store, prefixes: PrefixMap, uri: str, cache: _OxCurieCache | None = None
) -> Ref:
    """Build a Ref for any IRI in the store."""
    return Ref(eid=uri, curie=_ox_curie(prefixes, uri, cache), label=_ox_labels(store, uri))


def _ox_uri_refs(
    store: ox.Store,
    prefixes: PrefixMap,
    nodes: Iterable[_OxTerm],
    cache: _OxCurieCache | None = None,
) -> list[Ref]:
    """Map nodes to Refs, keeping only IRIs (blank nodes dropped)."""
    refs = [_ox_ref(store, prefixes, n.value, cache) for n in nodes if isinstance(n, ox.NamedNode)]
    return sorted(refs, key=lambda r: r.curie)


def _ox_is_class(store: ox.Store, uri: str) -> bool:
    return _ox_has(store, uri, terms.RDF_TYPE, terms.OWL_CLASS)


def _ox_ptype_of(store: ox.Store, uri: str) -> str:
    """ObjectProperty / DatatypeProperty / Property for a property entity."""
    for rdf_type, name in (
        (terms.OWL_OBJECTPROPERTY, "ObjectProperty"),
        (terms.OWL_DATATYPEPROPERTY, "DatatypeProperty"),
    ):
        if _ox_has(store, uri, terms.RDF_TYPE, rdf_type):
            return name
    return "Property"


def _ox_prop_ref(
    store: ox.Store, prefixes: PrefixMap, uri: str, cache: _OxCurieCache | None = None
) -> PropRef:
    """PropRef for a declared property IRI, with its domain/range classes."""
    return PropRef(
        **_ox_ref(store, prefixes, uri, cache).model_dump(),
        ptype=_ox_ptype_of(store, uri),
        domain=_ox_uri_refs(store, prefixes, _ox_objects(store, uri, terms.RDFS_DOMAIN), cache),
        range=_ox_uri_refs(store, prefixes, _ox_objects(store, uri, terms.RDFS_RANGE), cache),
    )


def _ox_ttl_literal(lit: ox.Literal) -> str:
    """One ox Literal as a Turtle quoted string with tag/datatype.

    ox materializes RDF 1.1 datatypes: a plain literal reports xsd:string
    and a tagged one rdf:langString, so the implicit forms are filtered
    here to keep rdflib-era output (bare "text" / "text"@lang).
    """
    text = "".join(_TTL_ESCAPES.get(ch, ch) for ch in lit.value)
    if lit.language:
        return f'"{text}"@{lit.language}'
    if lit.datatype != terms.XSD_STRING:
        return f'"{text}"^^<{lit.datatype.value}>'
    return f'"{text}"'


def _ox_ttl_term(
    prefixes: PrefixMap,
    term: _OxTerm,
    bindings: dict[str, str] | None = None,
    bnodes: dict[ox.BlankNode, str] | None = None,
    cache: _OxCurieCache | None = None,
) -> str:
    """One RDF term as Turtle: prefixed name, <iri>, literal or bnode.

    Prefixed renderings record their namespace in `bindings` (when given)
    so the caller can emit a self-contained block with @prefix lines; a
    `bnodes` map relabels blank nodes to _:b0, _:b1… by first appearance
    (raw ids are random per parse, which would break rebuild determinism).
    """
    if isinstance(term, ox.NamedNode):
        curie = _ox_curie_for(prefixes, term.value, cache)
        if curie is not None and curie[0] and _PN_LOCAL.match(curie[1]):
            if bindings is not None:
                # Namespace reconstructed from the split: uri == ns + local.
                bindings[curie[0]] = term.value[: len(term.value) - len(curie[1])]
            return f"{curie[0]}:{curie[1]}"
        return f"<{term.value}>"
    if isinstance(term, ox.Literal):
        return _ox_ttl_literal(term)
    if not isinstance(term, ox.BlankNode):
        return str(term)  # RDF-star quoted triple — N-Triples form
    if bnodes is None:
        return f"_:{term.value}"
    label = bnodes.get(term)
    if label is None:
        label = bnodes[term] = f"_:b{len(bnodes)}"
    return label


def _ox_turtle_block(
    store: ox.Store, prefixes: PrefixMap, uri: str, cache: _OxCurieCache | None = None
) -> str:
    """All triples with uri as subject, one self-contained Turtle block.

    Same shape as the rdflib _turtle_block above: grouped by predicate,
    used @prefix declarations leading the block, blank nodes relabeled.
    """
    by_pred: dict[str, tuple[ox.NamedNode, list[_OxTerm]]] = {}
    for q in store.quads_for_pattern(ox.NamedNode(uri), None, None, ox.DefaultGraph()):
        p = q.predicate
        entry = by_pred.get(p.value)
        if entry is None:
            by_pred[p.value] = (p, [q.object])
        else:
            entry[1].append(q.object)
    if not by_pred:
        return ""
    bindings: dict[str, str] = {}
    bnodes: dict[ox.BlankNode, str] = {}
    parts: list[str] = []
    for key in sorted(by_pred):
        p, objs = by_pred[key]
        pred = "a" if p == terms.RDF_TYPE else _ox_ttl_term(prefixes, p, bindings, bnodes, cache)
        rendered = sorted(_ox_ttl_term(prefixes, o, bindings, bnodes, cache) for o in objs)
        parts.append(f"{pred} " + " , ".join(rendered))
    subject = _ox_ttl_term(prefixes, ox.NamedNode(uri), bindings, bnodes, cache)
    text = f"{subject} {parts[0]}"
    for part in parts[1:]:
        text += f" ;\n    {part}"
    text += " ."
    header = "".join(
        f"@prefix {prefix}: <{namespace}> .\n" for prefix, namespace in sorted(bindings.items())
    )
    return f"{header}\n{text}" if header else text


def build_ir_store(store: ox.Store, prefixes: PrefixMap) -> IRBundle:
    """Walk the store's default graph once and assemble page-shaped entities.

    Same IR contract as build_ir (entities stay byte-identical); callers
    pass the parse_store output directly.
    """
    classes = sorted(
        s.value
        for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_CLASS)
        if isinstance(s, ox.NamedNode)
    )
    object_props: set[str] = set()
    datatype_props: set[str] = set()
    for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_OBJECTPROPERTY):
        if isinstance(s, ox.NamedNode):
            object_props.add(s.value)
    for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_DATATYPEPROPERTY):
        if isinstance(s, ox.NamedNode):
            datatype_props.add(s.value)
    props = sorted(object_props | datatype_props)

    entities: dict[str, EntityIR] = {}
    # One curie memo for the whole walk: entity curies, refs and axiom
    # blocks re-resolve the same URIs constantly.
    cc: _OxCurieCache = {}

    # Domain/range links walked once: props by class and classes by prop.
    props_by_class: dict[str, list[str]] = {}
    classes_by_prop: dict[str, list[tuple[str, str]]] = {}
    for p in props:
        for link, relation in (
            (terms.RDFS_DOMAIN, "rdfs:domain"),
            (terms.RDFS_RANGE, "rdfs:range"),
        ):
            for c in _ox_objects(store, p, link):
                if isinstance(c, ox.NamedNode):
                    props_by_class.setdefault(c.value, []).append(p)
                    classes_by_prop.setdefault(p, []).append((c.value, relation))

    # Declared entities (own classes and properties): the far ends the UI
    # may link into; everything else is external vocabulary.
    declared_uris = set(classes) | set(props)

    def _referenced(uri: str, is_class: bool, children: list[Ref]) -> list[ReferencedRef]:
        """Entities whose axioms mention uri: subclassers and domain/range peers."""

        def _counterpart(prop: str, relation: str) -> CounterpartRef | None:
            """The axiom's far end: range of prop for a domain ref, vice versa."""
            other = terms.RDFS_RANGE if relation == "rdfs:domain" else terms.RDFS_DOMAIN
            far = next(
                (o.value for o in _ox_objects(store, prop, other) if isinstance(o, ox.NamedNode)),
                None,
            )
            if far is None:
                return None
            return CounterpartRef(
                **_ox_ref(store, prefixes, far, cc).model_dump(), declared=far in declared_uris
            )

        refs = {
            r.eid: ReferencedRef(eid=r.eid, curie=r.curie, label=r.label, relation="subClassOf")
            for r in children
        }
        if is_class:
            for p in props_by_class.get(uri, []):
                base = _ox_ref(store, prefixes, p, cc)
                relation = (
                    "rdfs:domain"
                    if _ox_has(store, p, terms.RDFS_DOMAIN, ox.NamedNode(uri))
                    else "rdfs:range"
                )
                refs[base.eid] = ReferencedRef(
                    eid=base.eid,
                    curie=base.curie,
                    label=base.label,
                    relation=relation,
                    counterpart=_counterpart(p, relation),
                )
        else:
            for c, relation in classes_by_prop.get(uri, []):
                base = _ox_ref(store, prefixes, c, cc)
                refs[base.eid] = ReferencedRef(
                    eid=base.eid,
                    curie=base.curie,
                    label=base.label,
                    relation=relation,
                    counterpart=_counterpart(uri, relation),
                )
        return sorted(refs.values(), key=lambda r: r.curie)

    for uri in [*classes, *props]:
        is_class = _ox_is_class(store, uri)
        etype = "Class" if is_class else _ox_ptype_of(store, uri)

        parents = _ox_uri_refs(store, prefixes, _ox_objects(store, uri, terms.RDFS_SUBCLASSOF), cc)
        children = (
            _ox_uri_refs(
                store,
                prefixes,
                _ox_subjects(store, terms.RDFS_SUBCLASSOF, ox.NamedNode(uri)),
                cc,
            )
            if is_class
            else []
        )

        properties: list[PropRef] = []
        if is_class:
            for p in props_by_class.get(uri, []):
                properties.append(_ox_prop_ref(store, prefixes, p, cc))

        comment = next(
            (
                c.value
                for c in _ox_objects(store, uri, terms.RDFS_COMMENT)
                if isinstance(c, ox.Literal)
            ),
            None,
        )
        entities[uri] = EntityIR(
            eid=uri,
            curie=_ox_curie(prefixes, uri, cc),
            type=etype,
            label=_ox_labels(store, uri),
            comment=comment,
            deprecated=_ox_has(store, uri, terms.OWL_DEPRECATED, _OX_TRUE),
            parents=parents,
            children=children,
            properties=properties,
            referenced_by=_referenced(uri, is_class, children),
            axioms=[Axiom(turtle=_ox_turtle_block(store, prefixes, uri, cc))],
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

    # Default-graph triple count via SPARQL (len(store) would include
    # named-graph quads; the query's default graph is exactly DefaultGraph()
    # as long as use_default_graph_as_union stays off).
    results = store.query("SELECT (COUNT(*) AS ?c) WHERE { ?s ?p ?o }")
    assert isinstance(results, ox.QuerySolutions)
    count_row = next(iter(results))
    counts = Counts(
        class_count=len(classes),
        property_count=len(props),
        axiom_count=int(count_row["c"].value),
    )
    # Only namespaces the store actually uses (default-graph terms only);
    # PrefixMap seeds ~14 well-known entries, pruned by one explicit pass.
    used_iris: set[str] = set()
    _add_used = used_iris.add
    for q in store.quads_for_pattern(None, None, None, ox.DefaultGraph()):
        subj = q.subject
        pred = q.predicate
        obj = q.object
        if type(subj) is ox.NamedNode:
            _add_used(subj.value)
        if type(pred) is ox.NamedNode:
            _add_used(pred.value)
        if type(obj) is ox.NamedNode:
            _add_used(obj.value)
    prefixes_out = {
        p or "base": n
        for p, n in prefixes.as_dict().items()
        if any(iri.startswith(n) for iri in used_iris)
    }

    # Named individuals group under their declared rdf:type classes (direct
    # typing only — no subclass inference, matching the badge's direct count).
    class_set = set(classes)
    instances: dict[str, list[Ref]] = {}
    individuals_out: dict[str, IndividualIR] = {}
    individuals: set[str] = set()
    for ind in sorted(
        s.value
        for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL)
        if isinstance(s, ox.NamedNode)
    ):
        individuals.add(ind)
        comment = next(
            (
                c.value
                for c in _ox_objects(store, ind, terms.RDFS_COMMENT)
                if isinstance(c, ox.Literal)
            ),
            None,
        )
        cls: list[Ref] = []
        obj_asserts: list[ObjectAssertion] = []
        data_asserts: list[DataAssertion] = []
        for q in store.quads_for_pattern(ox.NamedNode(ind), None, None, ox.DefaultGraph()):
            pred = q.predicate
            obj = q.object
            if pred == terms.RDF_TYPE:
                if isinstance(obj, ox.NamedNode) and obj.value in class_set:
                    instances.setdefault(obj.value, []).append(_ox_ref(store, prefixes, ind, cc))
                    cls.append(_ox_ref(store, prefixes, obj.value, cc))
            elif (
                isinstance(pred, ox.NamedNode)
                and pred.value in object_props
                and isinstance(obj, ox.NamedNode)
            ):
                obj_asserts.append(
                    ObjectAssertion(
                        property=_ox_prop_ref(store, prefixes, pred.value, cc),
                        object=_ox_ref(store, prefixes, obj.value, cc),
                    )
                )
            elif (
                isinstance(pred, ox.NamedNode)
                and pred.value in datatype_props
                and isinstance(obj, ox.Literal)
                # rdflib's `datatype is not None` in ox terms: exclude the
                # implicit xsd:string form and language-tagged literals.
                and obj.language is None
                and obj.datatype != terms.XSD_STRING
            ):
                data_asserts.append(
                    DataAssertion(
                        property=_ox_prop_ref(store, prefixes, pred.value, cc),
                        value=obj.value,
                        datatype=obj.datatype.value,
                    )
                )
        individuals_out[ind] = IndividualIR(
            eid=ind,
            curie=_ox_curie(prefixes, ind, cc),
            label=_ox_labels(store, ind),
            comment=comment,
            classes=sorted(cls, key=lambda r: r.curie),
            object_assertions=sorted(obj_asserts, key=lambda a: a.property.curie),
            data_assertions=sorted(data_asserts, key=lambda a: a.property.curie),
        )

    counts.individual_count = len(individuals)

    # owl:Ontology subject IRI, deterministic under multiple declarations.
    onto_subjects = sorted(
        s.value
        for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_ONTOLOGY)
        if isinstance(s, ox.NamedNode)
    )
    return IRBundle(
        entities=entities,
        counts=counts,
        prefixes=prefixes_out,
        ontology_iri=onto_subjects[0] if onto_subjects else None,
        instances=instances,
        individuals=individuals_out,
    )
