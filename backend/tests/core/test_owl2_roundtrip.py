"""L0 保真:parse→serialize→parse 三元组集等价 + punning 不丢身份.

空节点标签每次 parse 重新生成(hash 内部 id),str 直比必假失败——
地面三元组精确比对;涉空节点三元组把空节点替换为按其非空宾语内容
算出的规范化哈希,等价判定仍严格到内容级.
"""

import hashlib
from pathlib import Path

import pyoxigraph as ox

from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.parsing import parse_store, serialize_store

SAMPLES = sorted((Path(__file__).parents[2] / "ontoworkbench" / "samples").glob("*.ttl"))
OWL2_NS = "https://github.com/skymacro111666/ontology-workbench/samples/owl2#"


def _bnode_key(store: ox.Store, node: ox.BlankNode) -> str:
    """Canonical id for a blank node: hash of its sorted non-blank object content."""
    parts = sorted(
        f"{q.predicate.value}|{q.object}"
        for q in store.quads_for_pattern(node, None, None, ox.DefaultGraph())
        if not isinstance(q.object, ox.BlankNode)
    )
    return "_:h" + hashlib.md5(";".join(parts).encode()).hexdigest()[:12]  # noqa: S324


def _term_key(store: ox.Store, term: object) -> str:
    if isinstance(term, ox.BlankNode):
        return _bnode_key(store, term)
    return str(term)


def _quads(store: ox.Store) -> set[tuple[str, str, str, str | None]]:
    out: set[tuple[str, str, str, str | None]] = set()
    for q in store.quads_for_pattern(None, None, None, ox.DefaultGraph()):
        datatype = q.object.datatype.value if isinstance(q.object, ox.Literal) else None
        triple = (
            _term_key(store, q.subject),
            q.predicate.value,
            _term_key(store, q.object),
            datatype,
        )
        out.add(triple)
    return out


def test_samples_exist() -> None:
    """owl2.ttl 进目录册:5 个既有样例 + 1 = 至少 6."""
    assert len(SAMPLES) >= 6
    assert any(p.name == "owl2.ttl" for p in SAMPLES)


def test_serialize_roundtrip_preserves_triples() -> None:
    """每个样例 parse→serialize→parse 后三元组集等价(含空节点内容规范化)."""
    for path in SAMPLES:
        store, prefixes = parse_store(path.read_bytes(), "turtle")
        data = serialize_store(store, prefixes, "turtle")
        again, _ = parse_store(data, "turtle")
        assert _quads(store) == _quads(again), f"roundtrip lost triples in {path.name}"


SAMPLE_OWL2 = Path(__file__).parents[2] / "ontoworkbench" / "samples" / "owl2.ttl"


def test_punning_survives_build_ir() -> None:
    """Genius 同 IRI 既是类又是个体:punning 下类页可见、个体身份不丢."""
    store, prefixes = parse_store(SAMPLE_OWL2.read_bytes(), "turtle")
    ir = build_ir_store(store, prefixes)
    genius = f"{OWL2_NS}Genius"
    assert genius in ir.entities  # 作为类可见
    assert ir.entities[genius].type == "Class"
    assert any("Genius" in a.turtle for a in ir.entities[genius].axioms)  # 个体身份不丢
