"""RDF→OWL 结构桥:pyoxigraph 子图 → RDF/XML → py-horned-owl.

纪律(spike 报告 2026-09-11):
- 解析错误以 pyo3 panic 穿透且非 Exception 子类,必须 except BaseException 收口;
- 未显式标类型的表达式空节点会被 horned-owl 静默丢弃(样本 47→39),normalize 预处理补类型;
- normalize 只作用于拷贝出的子 Store,共享池化 Store 永只读;
- 邻域收集必须展开空节点闭包,否则表达式树被截断.
"""

from __future__ import annotations

from typing import Any

import pyhornedowl
import pyoxigraph as ox

OWL = "http://www.w3.org/2002/07/owl#"
RDF_TYPE = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")

# 空节点带这些谓语 → 补 owl:Restriction 类型
_RESTRICTION_FILLERS = (
    "someValuesFrom",
    "allValuesFrom",
    "hasValue",
    "hasSelf",
    "cardinality",
    "minCardinality",
    "maxCardinality",
    "qualifiedCardinality",
    "minQualifiedCardinality",
    "maxQualifiedCardinality",
)
# 空节点带这些谓语 → 补 owl:Class 类型(布尔组合/枚举)
_CLASS_CONNECTIVES = ("unionOf", "intersectionOf", "complementOf", "oneOf")

_MAX_QUADS = 20_000


class Owl2BridgeError(Exception):
    """Bridge failure: parse panic, dump failure, or oversize fragment."""


def _bnode_closure(store: ox.Store, seeds: list[ox.BlankNode]) -> list[ox.BlankNode]:
    """Collect blank nodes reachable from seed nodes via any position (subject or object).

    返回节点对象而非标签:str(BlankNode) 带 "_:" 前缀,字符串往返会造出新节点导致失配.
    """
    seen: dict[str, ox.BlankNode] = {}
    frontier = list(seeds)
    while frontier:
        node = frontier.pop()
        key = str(node)
        if key in seen:
            continue
        seen[key] = node
        for q in store.quads_for_pattern(node, None, None, ox.DefaultGraph()):
            if isinstance(q.object, ox.BlankNode) and str(q.object) not in seen:
                frontier.append(q.object)
    return list(seen.values())


def _seed_bnodes(quad: ox.Quad) -> list[ox.BlankNode]:
    return [t for t in (quad.subject, quad.object) if isinstance(t, ox.BlankNode)]


def _subgraph(store: ox.Store, iri: str, max_quads: int) -> ox.Store:
    """Entity neighbourhood: quads where iri is subject or object, plus blank-node closures."""
    sub = ox.Store()
    term = ox.NamedNode(iri)
    seeds: list[ox.BlankNode] = []
    n = 0
    # iri 作主语;再作宾语(含 reified 公理的 annotatedSource/target)
    for pattern in ((term, None, None), (None, None, term)):
        s, p, o = pattern
        for q in store.quads_for_pattern(s, p, o, ox.DefaultGraph()):
            sub.add(q)
            n += 1
            seeds.extend(_seed_bnodes(q))
            if n >= max_quads:
                raise Owl2BridgeError(f"fragment budget exceeded ({max_quads} quads)")
    for node in _bnode_closure(store, seeds):
        for q in store.quads_for_pattern(node, None, None, ox.DefaultGraph()):
            sub.add(q)
    return sub


def _has_type(sub: ox.Store, node: ox.BlankNode) -> bool:
    return next(sub.quads_for_pattern(node, RDF_TYPE, None, ox.DefaultGraph()), None) is not None


def _normalize(sub: ox.Store) -> None:
    """补齐未显式标类型的表达式空节点(spike:否则整条公理被静默丢弃).

    先收集后写,避免边遍历边变异;已有 rdf:type 的不重复补.
    """
    restriction_preds = {ox.NamedNode(f"{OWL}{p}") for p in _RESTRICTION_FILLERS}
    class_preds = {ox.NamedNode(f"{OWL}{p}") for p in _CLASS_CONNECTIVES}
    to_type: list[tuple[ox.BlankNode, ox.NamedNode]] = []
    seen: set[str] = set()
    for q in sub.quads_for_pattern(None, None, None, ox.DefaultGraph()):
        for node in (q.subject, q.object):
            if not isinstance(node, ox.BlankNode) or str(node) in seen:
                continue
            seen.add(str(node))
            preds = {
                qq.predicate for qq in sub.quads_for_pattern(node, None, None, ox.DefaultGraph())
            }
            if preds & restriction_preds:
                to_type.append((node, ox.NamedNode(f"{OWL}Restriction")))
            elif preds & class_preds:
                to_type.append((node, ox.NamedNode(f"{OWL}Class")))
    for node, type_ in to_type:
        if not _has_type(sub, node):
            sub.add(ox.Quad(node, RDF_TYPE, type_, ox.DefaultGraph()))


def _dump(sub: ox.Store, prefixes: Any) -> str:
    table = prefixes.as_dict() if hasattr(prefixes, "as_dict") else prefixes
    try:
        out = sub.dump(format=ox.RdfFormat.RDF_XML, from_graph=ox.DefaultGraph(), prefixes=table)
    except BaseException as exc:  # ox dump 失败也统一收口
        raise Owl2BridgeError(str(exc)) from exc
    assert isinstance(out, bytes)  # dump 无 output 流时返回 bytes
    return out.decode()


def fragment(store: ox.Store, iri: str, prefixes: Any, *, max_quads: int = _MAX_QUADS) -> str:
    """Entity neighbourhood as RDF/XML (normalize 只作用于拷贝出的子 Store)."""
    sub = _subgraph(store, iri, max_quads)
    _normalize(sub)
    return _dump(sub, prefixes)


def whole(store: ox.Store, prefixes: Any) -> str:
    """Full store as RDF/XML(profile 判定等全量通路用)."""
    return _dump(store, prefixes)


def parse(xml: str) -> pyhornedowl.PyIndexedOntology:
    """RDF/XML → indexed ontology;panic 一律转 Owl2BridgeError(降级纪律的收口点)."""
    try:
        return pyhornedowl.open_ontology_from_string(xml, serialization="rdf")
    except BaseException as exc:  # PanicException 不是 Exception 子类(spike 实测)
        raise Owl2BridgeError(str(exc)) from exc
