"""Manchester 语法渲染:py-horned-owl 类型化公理 → 可读文本.

未识别的公理/表达式类型回落函数语法 str()(而非丢弃);整个入口失败返回
None,调用方显示既有 raw Turtle(降级纪律).

属性名以 py-horned-owl 1.4.1 dir() 实测为准(2026-09-11):
SubClassOf/.sub .sup;cardinality 族/.ope .bce .n;EquivalentClasses/.first(列表);
DisjointUnion/.first(头类) .second(列表);HasKey/.ce .vpe;组合表达式的
操作数统一在 .first(标量或列表,经 _as_list 归一).
"""

from __future__ import annotations

from typing import Any

import pyoxigraph as ox

from ..ir import _ox_curie
from .bridge import Owl2BridgeError, fragment, parse


def _as_list(v: Any) -> list[Any]:
    return list(v) if isinstance(v, (list, tuple)) else [v]


# 命名条目(非表达式):统一 curie 缩写
_NAMED = (
    "Class",
    "ObjectProperty",
    "DataProperty",
    "AnnotationProperty",
    "NamedIndividual",
    "Datatype",
)
_CARD_KW = {
    "ObjectMinCardinality": "min",
    "ObjectMaxCardinality": "max",
    "ObjectExactCardinality": "exactly",
}


def _c(prefixes: Any, v: Any) -> str:
    """NamedNode/Literal → curie 缩写(与实体页口径一致).

    PrefixMap → _ox_curie(仓库统一口径);裸 dict(测试态)→ 取本地名
    (# 或 / 后段);空表不回落全 IRI,保证行文可读.
    """
    s = str(v)
    if not s.startswith("http"):
        return s
    if hasattr(prefixes, "curie_for"):
        return _ox_curie(prefixes, s)
    return s.rsplit("#", 1)[-1].rsplit("/", 1)[-1]


def _expr(node: Any, prefixes: Any) -> str:
    """类表达式 → Manchester;未识别类型回落函数语法 str()(不丢信息)."""
    t = type(node).__name__

    def e(x: Any) -> str:
        return _expr(x, prefixes)

    if t in _NAMED:
        return _c(prefixes, getattr(node, "iri", node))
    if t in ("ObjectSomeValuesFrom", "ObjectAllValuesFrom"):
        kw = "some" if t.endswith("SomeValuesFrom") else "only"
        return f"{e(node.ope)} {kw} {e(node.bce)}"
    if t in _CARD_KW:
        return f"{e(node.ope)} {_CARD_KW[t]} {node.n} {e(node.bce)}"
    if t == "ObjectHasSelf":
        return f"{e(node.first)} Self"
    if t == "ObjectIntersectionOf":
        return " and ".join(e(x) for x in _as_list(node.first))
    if t == "ObjectUnionOf":
        # 并在交语境里优先级低,加括号防歧义(Manchester 惯例)
        return f"({' or '.join(e(x) for x in _as_list(node.first))})"
    if t == "ObjectComplementOf":
        return f"not {e(node.first)}"
    if t == "ObjectOneOf":
        members = ", ".join(_c(prefixes, getattr(x, "iri", x)) for x in _as_list(node.first))
        return "{" + members + "}"
    if t == "ObjectPropertyChain":
        return " ∘ ".join(e(x) for x in _as_list(node.first))
    return str(node)  # 兜底:HasValue/DatatypeRestriction/数据表达式等仍可读


def _axiom(ax: Any, prefixes: Any) -> str | None:
    """公理 → Manchester 一行;Declaration/Annotation 跳过(详情页已有专门区)."""
    t = type(ax).__name__
    if t == "AnnotatedComponent":
        ax = ax.component
        t = type(ax).__name__
    if t.startswith("Declare") or t == "OntologyAnnotation":
        return None
    if t == "AnnotationAssertion":
        return None

    def e(x: Any) -> str:
        return _expr(x, prefixes)

    if t == "SubClassOf":
        return f"{e(ax.sub)} SubClassOf {e(ax.sup)}"
    if t == "SubObjectPropertyOf":
        # 属性链在此 binding 里是裸 list(无 ObjectPropertyChain 包装)
        sub_s = (
            "chain(" + " ∘ ".join(e(x) for x in ax.sub) + ")"
            if isinstance(ax.sub, list)
            else e(ax.sub)
        )
        return f"{sub_s} SubPropertyOf {e(ax.sup)}"
    if t == "EquivalentClasses":
        ops = _as_list(ax.first)
        return f"{e(ops[0])} EquivalentTo {', '.join(e(x) for x in ops[1:])}"
    if t == "DisjointClasses":
        return f"DisjointClasses ({', '.join(e(x) for x in _as_list(ax.first))})"
    if t == "DisjointUnion":
        rest = ", ".join(e(x) for x in _as_list(ax.second))
        return f"{e(ax.first)} DisjointUnionOf ({rest})"
    if t == "HasKey":
        props = ", ".join(e(x) for x in _as_list(ax.vpe))
        return f"{e(ax.ce)} HasKey ({props})"
    if t == "ClassAssertion":
        return f"{e(ax.i)} Type {e(ax.ce)}"
    if t == "NegativeObjectPropertyAssertion":
        return f"{_c(prefixes, ax.source)} not {e(ax.ope)} {_c(prefixes, ax.target)}"
    if t in (
        "ReflexiveObjectProperty",
        "IrreflexiveObjectProperty",
        "SymmetricObjectProperty",
        "AsymmetricObjectProperty",
        "TransitiveObjectProperty",
        "FunctionalObjectProperty",
        "InverseFunctionalObjectProperty",
    ):
        word = t.removesuffix("ObjectProperty")
        return f"{e(ax.first)} {word}"
    return str(ax) or None  # 未识别公理:函数语法整行保留


def entity_manchester(store: ox.Store, iri: str, prefixes: Any) -> list[str] | None:
    """实体邻域公理 → Manchester 行列表;桥失败或零公理 → None(调用方降级)."""
    try:
        ont = parse(fragment(store, iri, prefixes))
    except Owl2BridgeError:
        return None
    out: list[str] = []
    for ax in ont.get_axioms_for_iri(iri):
        text = _axiom(ax, prefixes)
        if text:
            out.append(text)
    return out or None
