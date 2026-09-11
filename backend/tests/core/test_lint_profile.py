"""profile-exit 规则(T7):词表级 profile 判定证据转 lint findings."""

from pathlib import Path

from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.lint import RULES, run_rule
from ontoworkbench.core.parsing import parse_store

OWL = "http://www.w3.org/2002/07/owl#"

RDFS_MINI = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing .
"""


def _run(src: str):
    store, prefixes = parse_store(src.encode(), "turtle")
    ir = build_ir_store(store, prefixes)
    return run_rule("profile-exit", store, ir)


def test_registry_carries_tenth_rule() -> None:
    """内置规则 9 → 10;profile-exit 默认 warning."""
    assert "profile-exit" in RULES
    assert RULES["profile-exit"].severity == "warning"


def test_owl2_fixture_yields_findings_with_axiom_text() -> None:
    """带限定基数+disjointUnion 的 fixture:findings ≥1,证据与目标齐备."""
    data = Path("tests/fixtures/owl2-constructs.ttl").read_bytes()
    store, prefixes = parse_store(data, "turtle")
    ir = build_ir_store(store, prefixes)
    res = run_rule("profile-exit", store, ir)
    assert res.total >= 1
    assert all(f.severity == "warning" for f in res.findings)
    assert all("axiom" in f.params and "profile" in f.params for f in res.findings)
    joined = " ".join(f.params["axiom"] for f in res.findings)
    assert "qualifiedCardinality" in joined
    # subject 可点击定位:违规三元组的主语(声明过的实体 IRIs 至少一条)
    assert any(f.subject.startswith("http") for f in res.findings)


def test_pure_rdfs_zero_findings() -> None:
    """纯 RDFS 语料:top=EL 零违规 → 0 findings."""
    res = _run(RDFS_MINI)
    assert res.total == 0
    assert res.findings == []
