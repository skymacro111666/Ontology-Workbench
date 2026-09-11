"""bridge: pyoxigraph 子图 → RDF/XML → py-horned-owl,含 normalize 预处理纪律."""

from pathlib import Path

import pyoxigraph as ox
import pytest

from ontoworkbench.core.owl2.bridge import Owl2BridgeError, fragment, parse, whole

FIX = Path("tests/fixtures/owl2-constructs.ttl")
FIX_UNTYPED = Path("tests/fixtures/owl2-constructs-untyped.ttl")


def _store(path: Path) -> ox.Store:
    store = ox.Store()
    store.load(path=str(path), format=ox.RdfFormat.TURTLE)
    return store


def test_fragment_contains_expression_closure() -> None:
    """Student 邻域的空节点闭包完整,parse 后限定基数公理可还原."""
    xml = fragment(_store(FIX), "http://example.org/owl2-spike#Student", {})
    ont = parse(xml)
    texts = [str(a) for a in ont.get_axioms_for_iri("http://example.org/owl2-spike#Student")]
    assert any("ObjectExactCardinality(1" in t for t in texts)


def test_normalize_recovers_untyped_blank_nodes() -> None:
    """未标类型的对照版:normalize 补类型后,公理不再被静默丢弃(spike 47→39 伤)."""
    xml = fragment(_store(FIX_UNTYPED), "http://example.org/owl2-spike#Undergrad", {})
    ont = parse(xml)
    texts = [str(a) for a in ont.get_axioms_for_iri("http://example.org/owl2-spike#Undergrad")]
    assert any("ObjectIntersectionOf" in t for t in texts)  # 原版这里被静默丢弃


def test_parse_bad_xml_raises_bridge_error_not_panic() -> None:
    """解析 panic 以 BaseException 穿透且非 Exception 子类,必须收口为 Owl2BridgeError."""
    with pytest.raises(Owl2BridgeError):
        parse("this is not xml at all")


def test_source_store_not_mutated() -> None:
    """共享池化 Store 永只读:fragment 前后 quad 集不变(normalize 只碰拷贝)."""
    store = _store(FIX_UNTYPED)
    before = sorted(str(q) for q in store.quads_for_pattern(None, None, None, None))
    fragment(store, "http://example.org/owl2-spike#Undergrad", {})
    after = sorted(str(q) for q in store.quads_for_pattern(None, None, None, None))
    assert before == after


def test_whole_roundtrip_axiom_count() -> None:
    """全量通路:typed fixture 47 条公理(spike 实测)全数还原."""
    ont = parse(whole(_store(FIX), {}))
    assert sum(1 for _ in ont.get_axioms()) >= 47
