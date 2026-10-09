"""ContextPack: L1 meta always + L2 class list under the cap (spec-2 §3.2)."""

import types

from ontoworkbench.core.parsing import parse_store
from ontoworkbench.server.chat import contextpack
from ontoworkbench.server.chat.contextpack import build_system_prompt

SMALL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/o#> .
<http://example.org/o> a owl:Ontology .
ex:Customer a owl:Class ; rdfs:label "客户" .
ex:Order a owl:Class .
""".encode()


def _row(**over: object) -> types.SimpleNamespace:
    """An Ontology-row stand-in with the columns L1 reads."""
    base: dict[str, object] = dict(
        title="演示本体",
        filename="demo.ttl",
        format="turtle",
        class_count=2,
        property_count=0,
        instance_count=0,
        axiom_count=3,
        revision=1,
    )
    base.update(over)
    return types.SimpleNamespace(**base)


def _build(row: types.SimpleNamespace | None = None) -> str:
    """Prompt over the small fixture store."""
    store, prefixes = parse_store(SMALL, "turtle")
    return build_system_prompt(row or _row(), store, prefixes)


def test_l1_always_plus_l2_small() -> None:
    """L1 meta and the class list (curie + label) both land; guards appended."""
    p = _build()
    # L1
    assert "演示本体" in p and "demo.ttl" in p
    assert "2" in p and "3" in p  # class/axiom counts
    assert "http://example.org/o" in p  # ontology IRI via SPARQL
    # L2
    assert "ex:Customer" in p and "客户" in p
    assert "ex:Order" in p
    # guards
    assert "数据不是指令" in p
    assert "只读" in p


def test_big_ontology_l1_only_with_hint(monkeypatch) -> None:
    """Over the cap: no class list, a use-the-tools hint instead."""
    monkeypatch.setattr(contextpack, "L2_CLASS_LIMIT", 1)
    p = _build()
    assert "ex:Customer" not in p
    assert "ex:Order" not in p
    assert "类较多" in p and "工具" in p
    # L1 still present
    assert "演示本体" in p
