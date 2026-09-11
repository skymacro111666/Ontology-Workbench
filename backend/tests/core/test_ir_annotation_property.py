"""AnnotationProperty 第四 kind:收集/ptype/计数/编辑面排除."""

from pathlib import Path

import pyoxigraph as ox

from ontoworkbench.core.indexes import Indexes
from ontoworkbench.core.ir import IRBundle, build_ir_store
from ontoworkbench.core.parsing import parse_store

FIX = Path("tests/fixtures/owl2-constructs.ttl")
NS = "http://example.org/owl2-spike#"
SAMPLES = sorted((Path(__file__).parents[2] / "ontoworkbench" / "samples").glob("*.ttl"))


def _ir(path: Path) -> IRBundle:
    store, prefixes = parse_store(path.read_bytes(), "turtle")
    return build_ir_store(store, prefixes)


def test_annotation_property_collected_as_fourth_kind() -> None:
    """:difficulty 成为实体,type == AnnotationProperty(第四 kind)."""
    ir = _ir(FIX)
    difficulty = f"{NS}difficulty"
    assert difficulty in ir.entities
    assert ir.entities[difficulty].type == "AnnotationProperty"
    # 其 AnnotationAssertion(Student 的 "moderate")进 axiom 块
    assert any("moderate" in a.turtle for a in ir.entities[difficulty].axioms)


def test_annotation_property_counts_and_sidebar_visibility() -> None:
    """非 Class 实体 = 侧栏属性页口径;计数含标注属性."""
    ir = _ir(FIX)
    non_class = [e for e in ir.entities.values() if e.type != "Class"]
    assert {e.type for e in non_class} >= {
        "ObjectProperty",
        "DatatypeProperty",
        "AnnotationProperty",
    }
    assert ir.counts.property_count == len(non_class)


def test_samples_build_ir_regression() -> None:
    """全部样例(含 owl2)build_ir 不破;foaf 计数含 7 个标注属性."""
    for path in SAMPLES:
        ir = _ir(path)
        assert ir.counts.class_count > 0, path.name
    foaf = _ir(next(p for p in SAMPLES if p.name == "foaf.ttl"))
    kinds = {e.type for e in foaf.entities.values()}
    assert "AnnotationProperty" in kinds


def test_assertion_schema_excludes_annotation_properties() -> None:
    """实例编辑面不扩:assertion schema 不收标注属性(spec 决策)."""
    store, prefixes = parse_store(FIX.read_bytes(), "turtle")
    ir = build_ir_store(store, prefixes)
    ix = Indexes(ir)
    schema = ix.assertion_schema([f"{NS}Student"])
    assert f"{NS}difficulty" not in schema


def test_source_store_untouched_and_punning_safe() -> None:
    """Build 后 store 仍可再 build(幂等),空节点断言不污染."""
    store: ox.Store
    store, prefixes = parse_store(FIX.read_bytes(), "turtle")
    ir1 = build_ir_store(store, prefixes)
    ir2 = build_ir_store(store, prefixes)
    assert ir1.counts == ir2.counts
