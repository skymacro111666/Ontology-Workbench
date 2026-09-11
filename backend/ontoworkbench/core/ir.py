"""IR models + assembly from a pyoxigraph Store (build_ir_store).

The IR is the stable contract between parsing and all consumers
(API, exporter, future MCP). It is 'page-shaped': one entity carries
everything its detail page needs.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass

import pyoxigraph as ox
from pydantic import BaseModel

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
    type: str  # Class | ObjectProperty | DatatypeProperty | AnnotationProperty | Property
    label: dict[str, str] = {}
    comment: str | None = None
    deprecated: bool = False
    parents: list[Ref] = []
    children: list[Ref] = []
    properties: list[PropRef] = []
    referenced_by: list[ReferencedRef] = []
    axioms: list[Axiom] = []
    # Manchester 渲染按请求惰性现算(OWL 2 M1 spec:不进 IR 缓存),详情
    # 路由浅拷贝填充;None = 桥失败或零公理 → 前端不显示公理区(降级).
    manchester: list[str] | None = None
    stats: Stats = Stats()
    kind: str = "entity"


class ObjectAssertion(BaseModel):
    """实例 → 另一实例(谓词为已声明 ObjectProperty)."""

    property: PropRef
    object: Ref


class DataAssertion(BaseModel):
    """实例 → 字面量(谓词为已声明 DatatypeProperty,无语言标签;datatype 为完整 IRI)."""

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


_TTL_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# Conservative PN_LOCAL whitelist; anything else renders as <iri> (always valid).
_PN_LOCAL = re.compile(r"[A-Za-z0-9_](?:[A-Za-z0-9_\-.]*[A-Za-z0-9_\-])?\Z")


# IR semantics are triple/default-graph: every traversal pins
# ox.DefaultGraph() (bare Store iteration would leak named-graph quads),
# and axiom_count is a SPARQL COUNT over the default graph rather than
# len(store) for the same reason.

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
    """ObjectProperty / DatatypeProperty / AnnotationProperty / Property for a property entity."""
    for rdf_type, name in (
        (terms.OWL_OBJECTPROPERTY, "ObjectProperty"),
        (terms.OWL_DATATYPEPROPERTY, "DatatypeProperty"),
        (terms.OWL_ANNOTATIONPROPERTY, "AnnotationProperty"),
    ):
        if _ox_has(store, uri, terms.RDF_TYPE, rdf_type):
            return name
    return "Property"


def _has_any_type(store: ox.Store, uri: str) -> bool:
    """Whether uri carries any rdf:type quad in the default graph."""
    pattern = store.quads_for_pattern(ox.NamedNode(uri), terms.RDF_TYPE, None, ox.DefaultGraph())
    return next(pattern, None) is not None


def _alive_kind(store: ox.Store, uri: str) -> str | None:
    """Liveness/kind of an entity for refresh: Class, property ptype, or None.

    Mirrors how build collects entities (classes plus explicitly typed
    Object/Datatype properties — the props set): a Class is alive, a
    property only with explicit ObjectProperty/DatatypeProperty typing,
    anything else (no rdf:type quad at all, or residual typing such as a
    bare owl:Property) is gone.
    """
    if _ox_is_class(store, uri):
        return "Class"
    if not _has_any_type(store, uri):
        return None
    ptype = _ox_ptype_of(store, uri)
    return None if ptype == "Property" else ptype


def _individuals_typed_at(store: ox.Store, cls: str) -> list[str]:
    """Individual eids currently typed at cls, sorted (the build's bucket order)."""
    return sorted(
        s.value
        for s in _ox_subjects(store, terms.RDF_TYPE, ox.NamedNode(cls))
        if isinstance(s, ox.NamedNode)
        and _ox_has(store, s.value, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL)
    )


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
    here to keep the bare forms ("text" / "text"@lang).
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
        # curie[0] may be "" (the default namespace, `@prefix :`): ":Dog" is
        # valid Turtle, with bindings[""] emitting `@prefix : <ns> .`
        if curie is not None and _PN_LOCAL.match(curie[1]):
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

    Grouped by predicate, used @prefix declarations leading the block,
    blank nodes relabeled to first-appearance order.
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


@dataclass
class _WalkCtx:
    """Per-walk indexes shared by build_ir_store and the refresh API.

    Built once per pass (_build_ctx): the declared class/property
    membership sets and the domain/range link tables, so per-entity
    extraction (_entity_ir/_individual_ir) rescans nothing.
    """

    classes: set[str]
    object_props: set[str]
    datatype_props: set[str]
    # Fourth kind (OWL 2 M1): annotation properties are entities (sidebar/
    # detail/docs surfaces) but stay out of the domain/range link tables —
    # annotations are not structural links, so the canvas never draws them.
    annotation_props: set[str]
    # Declared entities (own classes and properties): the far ends the UI
    # may link into; everything else is external vocabulary.
    declared: set[str]
    props_by_class: dict[str, list[str]]
    classes_by_prop: dict[str, list[tuple[str, str]]]


def _build_ctx(store: ox.Store) -> _WalkCtx:
    """Scan declared classes/properties and their domain/range links once."""
    classes = sorted(
        s.value
        for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_CLASS)
        if isinstance(s, ox.NamedNode)
    )
    object_props: set[str] = set()
    datatype_props: set[str] = set()
    annotation_props: set[str] = set()
    for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_OBJECTPROPERTY):
        if isinstance(s, ox.NamedNode):
            object_props.add(s.value)
    for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_DATATYPEPROPERTY):
        if isinstance(s, ox.NamedNode):
            datatype_props.add(s.value)
    for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_ANNOTATIONPROPERTY):
        if isinstance(s, ox.NamedNode):
            annotation_props.add(s.value)
    # Domain/range links are structural: object/data properties only.
    props = sorted(object_props | datatype_props)

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

    return _WalkCtx(
        classes=set(classes),
        object_props=object_props,
        datatype_props=datatype_props,
        annotation_props=annotation_props,
        declared=set(classes) | set(props) | annotation_props,
        props_by_class=props_by_class,
        classes_by_prop=classes_by_prop,
    )


def _referenced(
    store: ox.Store,
    prefixes: PrefixMap,
    uri: str,
    is_class: bool,
    children: list[Ref],
    ctx: _WalkCtx,
    cc: _OxCurieCache,
) -> list[ReferencedRef]:
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
            **_ox_ref(store, prefixes, far, cc).model_dump(), declared=far in ctx.declared
        )

    refs = {
        r.eid: ReferencedRef(eid=r.eid, curie=r.curie, label=r.label, relation="subClassOf")
        for r in children
    }
    if is_class:
        for p in ctx.props_by_class.get(uri, []):
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
        for c, relation in ctx.classes_by_prop.get(uri, []):
            base = _ox_ref(store, prefixes, c, cc)
            refs[base.eid] = ReferencedRef(
                eid=base.eid,
                curie=base.curie,
                label=base.label,
                relation=relation,
                counterpart=_counterpart(uri, relation),
            )
    return sorted(refs.values(), key=lambda r: r.curie)


def _entity_ir(
    store: ox.Store, prefixes: PrefixMap, uri: str, cc: _OxCurieCache, ctx: _WalkCtx
) -> EntityIR:
    """One entity's page-shaped extraction (shared by full build and refresh)."""
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
        for p in ctx.props_by_class.get(uri, []):
            properties.append(_ox_prop_ref(store, prefixes, p, cc))

    comment = next(
        (c.value for c in _ox_objects(store, uri, terms.RDFS_COMMENT) if isinstance(c, ox.Literal)),
        None,
    )
    axiom_blocks = [Axiom(turtle=_ox_turtle_block(store, prefixes, uri, cc))]
    if etype == "AnnotationProperty":
        usage = _annotation_usage_block(store, prefixes, uri, cc)
        if usage:
            axiom_blocks.append(Axiom(turtle=usage))
    return EntityIR(
        eid=uri,
        curie=_ox_curie(prefixes, uri, cc),
        type=etype,
        label=_ox_labels(store, uri),
        comment=comment,
        deprecated=_ox_has(store, uri, terms.OWL_DEPRECATED, _OX_TRUE),
        parents=parents,
        children=children,
        properties=properties,
        referenced_by=_referenced(store, prefixes, uri, is_class, children, ctx, cc),
        axioms=axiom_blocks,
        stats=Stats(direct_children=len(children)),
    )


def _annotation_usage_block(
    store: ox.Store, prefixes: PrefixMap, uri: str, cc: _OxCurieCache | None = None
) -> str:
    """Annotation usages (uri as predicate), one Turtle block, 50-line cap.

    属性实体的主语象限声明已由 _ox_turtle_block 覆盖;标注属性的「用法」
    (作谓语的断言)是它的核心内容,单列一块(带截断计数,防大本体爆页).
    """
    lines: list[str] = []
    total = 0
    pred_curie = _ox_curie(prefixes, uri, cc)
    for q in store.quads_for_pattern(None, ox.NamedNode(uri), None, ox.DefaultGraph()):
        total += 1
        if len(lines) >= 50:
            continue
        subj = _ox_ttl_term(prefixes, q.subject, None, None, cc)
        obj = _ox_ttl_term(prefixes, q.object, None, None, cc)
        lines.append(f"{subj} {pred_curie} {obj} .")
    if not lines:
        return ""
    if total > len(lines):
        lines.append(f"# … {total - len(lines)} more uses truncated")
    return "\n".join(lines)


def _individual_ir(
    store: ox.Store, prefixes: PrefixMap, ind: str, ctx: _WalkCtx, cc: _OxCurieCache
) -> tuple[IndividualIR, list[str]]:
    """One individual's extraction plus its direct class eids.

    The class → instances rows are placed by the caller (build walks all
    individuals in sorted order; refresh regroups a single one).
    """
    comment = next(
        (c.value for c in _ox_objects(store, ind, terms.RDFS_COMMENT) if isinstance(c, ox.Literal)),
        None,
    )
    cls: list[Ref] = []
    obj_asserts: list[ObjectAssertion] = []
    data_asserts: list[DataAssertion] = []
    for q in store.quads_for_pattern(ox.NamedNode(ind), None, None, ox.DefaultGraph()):
        pred = q.predicate
        obj = q.object
        if pred == terms.RDF_TYPE:
            if isinstance(obj, ox.NamedNode) and obj.value in ctx.classes:
                cls.append(_ox_ref(store, prefixes, obj.value, cc))
        elif (
            isinstance(pred, ox.NamedNode)
            and pred.value in ctx.object_props
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
            and pred.value in ctx.datatype_props
            and isinstance(obj, ox.Literal)
            # RDF 1.1: a bare literal IS xsd:string, so string assertions
            # count too (the instance editor's default datatype), with
            # the full datatype IRI; only language-tagged literals stay out.
            and obj.language is None
        ):
            data_asserts.append(
                DataAssertion(
                    property=_ox_prop_ref(store, prefixes, pred.value, cc),
                    value=obj.value,
                    datatype=obj.datatype.value,
                )
            )
    classes_sorted = sorted(cls, key=lambda r: r.curie)
    return (
        IndividualIR(
            eid=ind,
            curie=_ox_curie(prefixes, ind, cc),
            label=_ox_labels(store, ind),
            comment=comment,
            classes=classes_sorted,
            object_assertions=sorted(obj_asserts, key=lambda a: a.property.curie),
            data_assertions=sorted(data_asserts, key=lambda a: a.property.curie),
        ),
        [c.eid for c in classes_sorted],
    )


def build_ir_store(store: ox.Store, prefixes: PrefixMap) -> IRBundle:
    """Walk the store's default graph once and assemble page-shaped entities.

    Built straight from the pyoxigraph Store + PrefixMap (parse_store
    output) — there is no intermediate graph model.
    """
    ctx = _build_ctx(store)
    classes = sorted(ctx.classes)
    # property_count covers every non-class entity kind (sidebar's props
    # tab lists exactly these): object + datatype + annotation.
    props = sorted(ctx.object_props | ctx.datatype_props | ctx.annotation_props)

    entities: dict[str, EntityIR] = {}
    # One curie memo for the whole walk: entity curies, refs and axiom
    # blocks re-resolve the same URIs constantly.
    cc: _OxCurieCache = {}
    for uri in [*classes, *props]:
        entities[uri] = _entity_ir(store, prefixes, uri, cc, ctx)

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
        p: n for p, n in prefixes.as_dict().items() if any(iri.startswith(n) for iri in used_iris)
    }

    # Named individuals group under their declared rdf:type classes (direct
    # typing only — no subclass inference, matching the badge's direct count).
    instances: dict[str, list[Ref]] = {}
    individuals_out: dict[str, IndividualIR] = {}
    individuals: set[str] = set()
    for ind in sorted(
        s.value
        for s in _ox_subjects(store, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL)
        if isinstance(s, ox.NamedNode)
    ):
        individuals.add(ind)
        ind_ir, class_eids = _individual_ir(store, prefixes, ind, ctx, cc)
        individuals_out[ind] = ind_ir
        for c in class_eids:
            instances.setdefault(c, []).append(
                Ref(eid=ind_ir.eid, curie=ind_ir.curie, label=ind_ir.label)
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


def affected_around(ir: IRBundle, store: ox.Store, prefixes: PrefixMap, eid: str) -> set[str]:
    """Closed neighborhood of eid across the old IR and the mutated store.

    One union, two directions: the IR's own links (parents, children,
    referenced_by, property domain/range peers) catch entities whose
    pages mention eid, while fresh subClassOf/domain/range edges from the
    store catch counterparts the pre-mutation IR has never seen. Refresh
    over this set keeps the incremental bundle equal to a full rebuild.
    """
    out = {eid}
    e = ir.entities.get(eid)
    if e:
        out.update(r.eid for r in e.parents)
        out.update(r.eid for r in e.children)
        out.update(r.eid for r in e.referenced_by)
        for p in e.properties:
            out.update(r.eid for r in p.domain)
            out.update(r.eid for r in p.range)
    for pred in (terms.RDFS_SUBCLASSOF, terms.RDFS_DOMAIN, terms.RDFS_RANGE):
        for o in _ox_objects(store, eid, pred):
            if isinstance(o, ox.NamedNode):
                out.add(o.value)
        for s in _ox_subjects(store, pred, ox.NamedNode(eid)):
            if isinstance(s, ox.NamedNode):
                out.add(s.value)
    return out


def recompute_descendants(ir: IRBundle, seeds: Iterable[str]) -> None:
    """Redo total_descendants for seeds and every ancestor above them.

    direct_children is authoritative on each entity (refresh already
    re-extracted it); totals are a memoized DFS over the children lists,
    cycle-guarded the same way as the build pass.
    """
    memo: dict[str, int] = {}

    def _total(eid: str) -> int:
        if eid in memo:
            return memo[eid]
        memo[eid] = 0  # cycle guard
        e = ir.entities.get(eid)
        memo[eid] = sum(1 + _total(c.eid) for c in e.children) if e else 0
        return memo[eid]

    upstream: set[str] = set()
    stack = list(seeds)
    while stack:
        cur = stack.pop()
        if cur in upstream:
            continue
        upstream.add(cur)
        e = ir.entities.get(cur)
        if e:
            stack.extend(p.eid for p in e.parents)
    # Sorted entry, not set order: under a subClassOf cycle the guard fixes
    # whichever node the DFS reaches first, so values must not vary with
    # hash randomization. Sorted matches the build's own sorted class
    # walk; DAG totals are entry-order independent anyway.
    for eid in sorted(upstream):
        e = ir.entities.get(eid)
        if e:
            e.stats = Stats(direct_children=e.stats.direct_children, total_descendants=_total(eid))


def refresh_entities(
    ir: IRBundle, store: ox.Store, prefixes: PrefixMap, affected: set[str]
) -> None:
    """Re-extract the affected entities from store; drop the ones that vanished.

    The refresh cascades to the individuals referencing an affected
    entity: a surviving class rebuilds its instances bucket from the
    individuals currently typed at it, a dead class loses its bucket,
    and every individual carrying an affected property's quads is
    refreshed — so buckets, class lists and assertions stay equal to a
    full rebuild. counts are the caller's to maintain (one owner: the
    mutation handler bumps class/property deltas itself; axiom_count is
    re-counted when persisting). Descendant totals are recomputed for
    the whole affected ancestry.
    """
    cc: _OxCurieCache = {}
    ctx = _build_ctx(store)
    # Individuals whose rows or pages reference an affected entity; they
    # are refreshed after the entity pass so re-extraction sees final state.
    touched: set[str] = set()
    for eid in sorted(affected):
        kind = _alive_kind(store, eid)
        if kind == "Class":
            ir.entities[eid] = _entity_ir(store, prefixes, eid, cc, ctx)
            typed = _individuals_typed_at(store, eid)
            if typed:
                ir.instances[eid] = [_ox_ref(store, prefixes, s, cc) for s in typed]
            else:
                ir.instances.pop(eid, None)
            touched.update(typed)
        elif kind is not None:
            ir.entities[eid] = _entity_ir(store, prefixes, eid, cc, ctx)
        else:
            ir.entities.pop(eid, None)
            ir.instances.pop(eid, None)
            # the entity is gone, but typing quads may still point at it
            touched.update(_individuals_typed_at(store, eid))
        if kind != "Class":
            # assertion quads carrying this property: their subjects' pages
            # gain/lose the assertion as the property appears or vanishes
            for q in store.quads_for_pattern(None, ox.NamedNode(eid), None, ox.DefaultGraph()):
                s = q.subject
                if isinstance(s, ox.NamedNode) and _ox_has(
                    store, s.value, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL
                ):
                    touched.add(s.value)
    for ind in sorted(touched):
        _regroup_individual(ir, store, prefixes, ind, ctx, cc)
    recompute_descendants(ir, affected)


def _drop_instance_row(ir: IRBundle, cls: str, eid: str) -> None:
    """Remove eid's row from the class bucket, dropping emptied buckets."""
    rows = ir.instances.get(cls)
    if rows is not None:
        rows = [r for r in rows if r.eid != eid]
        if rows:
            ir.instances[cls] = rows
        else:
            del ir.instances[cls]


def _regroup_individual(
    ir: IRBundle,
    store: ox.Store,
    prefixes: PrefixMap,
    eid: str,
    ctx: _WalkCtx,
    cc: _OxCurieCache,
) -> None:
    """refresh_individual core over a shared walk context (no per-call scans)."""
    old = ir.individuals.get(eid)
    old_classes = {r.eid for r in old.classes} if old else set()
    if not _ox_has(store, eid, terms.RDF_TYPE, terms.OWL_NAMEDINDIVIDUAL):
        for c in old_classes:
            _drop_instance_row(ir, c, eid)
        ir.individuals.pop(eid, None)
        return
    ind, class_eids = _individual_ir(store, prefixes, eid, ctx, cc)
    # Strip the current row from every bucket it could sit in — old classes
    # plus the new ones (a bucket may have been rebuilt directly by
    # refresh_entities) — then re-place: idempotent under any bucket state.
    for c in old_classes | set(class_eids):
        _drop_instance_row(ir, c, eid)
    ir.individuals[eid] = ind
    for c in class_eids:
        rows = ir.instances.setdefault(c, [])
        rows.append(Ref(eid=eid, curie=ind.curie, label=ind.label))
        rows.sort(key=lambda r: r.eid)  # build order: one row per sorted individual


def refresh_individual(ir: IRBundle, store: ox.Store, prefixes: PrefixMap, eid: str) -> None:
    """Rebuild one IndividualIR and regroup its class → instances rows.

    Liveness follows the build's collection rule (owl:NamedIndividual
    subjects); counts stay with the caller, same contract as
    refresh_entities.
    """
    _regroup_individual(ir, store, prefixes, eid, _build_ctx(store), {})
