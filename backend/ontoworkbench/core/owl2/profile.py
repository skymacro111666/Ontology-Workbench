"""OWL 2 profile 判定(词表级近似):纯 RDF 词表扫描.

对 W3C OWL 2 Profiles 规范的近似(2026-09-11 核对):
- 命中禁用词表即出界,不做位置敏感判定(QL 的 superclass-only complement、
  RL 的 superclass-only max 0/1 等位置规则一律忽略 → 词表允许);
- 元数不敏感(EL 允许单元素 oneOf、基数 0/1 的精确值不区分);
- 数据类型不查(EL/QL 的 xsd 禁用表、RL 的 owl:real/rational 不查);
- 匿名个体不查(EL/QL 均禁,结构判定超出词表口径);
- EL 的函数型属性特例精确到 RDF 类型可判:函数型对象属性出界,
  函数型数据属性在 EL 内(规范允许);
- QL 禁 sameAs(SameIndividual),词表级按谓词命中。

判定顺序 EL → QL → RL:首个全过的即 top(「能装下的最小 profile」),
三者全不过 → DL。输出恒带 approximate=True;violations 上限 200 条,
每条携带违规三元组的可读缩写与被它出卖的 profile 集。
"""

from __future__ import annotations

from typing import Any

import pyoxigraph as ox

from .render import _c

OWL = "http://www.w3.org/2002/07/owl#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

_ORDER = ("EL", "QL", "RL")
_MAX_VIOLATIONS = 200

BANS: dict[str, set[str]] = {
    # EL:全基数族/allValuesFrom/unionOf/complementOf/disjointUnionOf/inverse/
    #    symmetric/asymmetric/irreflexive/inverseFunctional/属性互斥
    "EL": {
        "allValuesFrom",
        "unionOf",
        "complementOf",
        "disjointUnionOf",
        "cardinality",
        "minCardinality",
        "maxCardinality",
        "qualifiedCardinality",
        "minQualifiedCardinality",
        "maxQualifiedCardinality",
        "inverseOf",
        "SymmetricProperty",
        "AsymmetricProperty",
        "IrreflexiveProperty",
        "InverseFunctionalProperty",
        "propertyDisjointWith",
        "AllDisjointProperties",
    },
    # QL:基数族/allValuesFrom/unionOf/disjointUnionOf/hasSelf/hasValue/oneOf/
    #    transitive/functional(含数据属性)/inverseFunctional/链/hasKey/
    #    负断言/sameAs
    "QL": {
        "allValuesFrom",
        "unionOf",
        "disjointUnionOf",
        "cardinality",
        "minCardinality",
        "maxCardinality",
        "qualifiedCardinality",
        "minQualifiedCardinality",
        "maxQualifiedCardinality",
        "hasSelf",
        "hasValue",
        "oneOf",
        "TransitiveProperty",
        "FunctionalProperty",
        "InverseFunctionalProperty",
        "propertyChainAxiom",
        "hasKey",
        "NegativePropertyAssertion",
        "sameAs",
    },
    # RL:min/exact 基数族(0/1 限值不区分)/disjointUnionOf/reflexive
    "RL": {
        "cardinality",
        "minCardinality",
        "qualifiedCardinality",
        "minQualifiedCardinality",
        "disjointUnionOf",
        "ReflexiveProperty",
    },
}

# 各 profile 词表的并集:扫描谓词与 rdf:type 对象两处命中
_ALL_BANNED = set().union(*BANS.values())


def _local(uri: str) -> str | None:
    """OWL 命名空间下的本地名;其余命名空间 None."""
    return uri[len(OWL) :] if uri.startswith(OWL) else None


def _val(term: Any) -> str:
    """Term 的字符串值:NamedNode/BlankNode/Literal → .value.

    Triple 不会出现在四元组的 s/p/o 位,getattr 兜底只为过类型关.
    """
    v = getattr(term, "value", None)
    return v if isinstance(v, str) else str(term)


def classify(store: ox.Store, prefixes: Any) -> dict[str, Any]:
    """词表级判定:{"top", "approximate", "axiom_count", "violations"}."""
    hits: list[tuple[str, str]] = []  # (三元组缩写, 命中的 OWL 本地名)
    functional: set[str] = set()
    axiom_count = 0
    for q in store.quads_for_pattern(None, None, None, None):
        axiom_count += 1
        # 注意 str(term) 是 N-Triples 形态(带 <>);统一走 _val
        p_local = _local(_val(q.predicate))
        if p_local in _ALL_BANNED:
            hits.append((_fmt(q, prefixes), p_local))
        o_local = _local(_val(q.object)) if isinstance(q.object, ox.NamedNode) else None
        if o_local in _ALL_BANNED:
            hits.append((_fmt(q, prefixes), o_local))
        if p_local == "FunctionalProperty" or o_local == "FunctionalProperty":
            functional.add(_val(q.subject))
    # EL 特例:函数型对象属性(或未标数据属性的函数型属性)出界
    el_functional: list[str] = []
    for s in sorted(functional):
        types = {
            _val(q.object)
            for q in store.quads_for_pattern(ox.NamedNode(s), ox.NamedNode(RDF_TYPE), None, None)
        }
        if f"{OWL}DatatypeProperty" not in types:
            el_functional.append(s)

    # 检查顺序 EL→QL→RL:首个全过的即 top;violations 只解释「top 为何
    # 不能更小」——顺序中在 top 之前落败的 profile 的证据(top 之后的
    # 落败不影响判定,不进 violations)。
    def _fails(profile: str) -> bool:
        return any(t in BANS[profile] for _, t in hits) or (profile == "EL" and bool(el_functional))

    failed: list[str] = []
    top: str | None = None
    for p in _ORDER:
        if _fails(p):
            failed.append(p)
        else:
            top = p
            break
    if top is None:
        top = "DL"

    violations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for text, term in hits:
        bans = sorted(p for p in failed if term in BANS[p])
        if bans and (text, term) not in seen:
            seen.add((text, term))
            violations.append({"axiom": text, "bans": bans})
        if len(violations) >= _MAX_VIOLATIONS:
            break
    if "EL" in failed:
        for s in el_functional[: max(0, _MAX_VIOLATIONS - len(violations))]:
            violations.append({"axiom": f"{_c(prefixes, s)} a FunctionalProperty", "bans": ["EL"]})
    return {"top": top, "approximate": True, "axiom_count": axiom_count, "violations": violations}


def _fmt(q: ox.Quad, prefixes: Any) -> str:
    """三元组缩写:rdf:type 行折成 "S a O",其余 "S P O"."""

    def c(t: Any) -> str:
        return _c(prefixes, _val(t))

    if _val(q.predicate) == RDF_TYPE:
        return f"{c(q.subject)} a {c(q.object)}"
    obj = q.object
    tail = f'"{obj.value}"' if isinstance(obj, ox.Literal) else c(obj)
    return f"{c(q.subject)} {c(q.predicate)} {tail}"
