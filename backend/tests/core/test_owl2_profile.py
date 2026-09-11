"""词表级 profile 判定:纯 RDF 词表扫描,输出恒带 approximate=True."""

import pyoxigraph as ox

from ontoworkbench.core.owl2.profile import classify

OWL = "http://www.w3.org/2002/07/owl#"

RDFS_MINI = """@prefix : <http://example.org/m#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
:Thing a <http://www.w3.org/2002/07/owl#Class> .
:Animal a <http://www.w3.org/2002/07/owl#Class> ; rdfs:subClassOf :Thing ; rdfs:label "Animal"@en .
"""


def _mini(text: str) -> ox.Store:
    """Inline Turtle → Store."""
    s = ox.Store()
    s.load(text, format=ox.RdfFormat.TURTLE)
    return s


def test_pure_rdfs_is_el() -> None:
    """纯 RDFS 迷你语料:top=EL,零违规,恒带近似标记."""
    v = classify(_mini(RDFS_MINI), {})
    assert v["top"] == "EL"
    assert v["approximate"] is True
    assert v["violations"] == []
    assert v["axiom_count"] >= 4


def test_owl2_fixture_is_dl_with_evidence() -> None:
    """带限定基数+disjointUnion 的 fixture:全落败 → DL,证据齐."""
    s = ox.Store()
    s.load(path="tests/fixtures/owl2-constructs.ttl", format=ox.RdfFormat.TURTLE)
    v = classify(s, {})
    assert v["top"] == "DL"
    joined = " ".join(x["axiom"] for x in v["violations"])
    assert "qualifiedCardinality" in joined
    assert "disjointUnionOf" in joined
    assert all(x["bans"] for x in v["violations"])


def test_symmetric_demotes_el_only() -> None:
    """EL 禁 symmetric,QL/RL 允许 → 检查顺序 EL→QL→RL 命中 QL."""
    text = RDFS_MINI + f":knows a <{OWL}SymmetricProperty> .\n"
    v = classify(_mini(text), {})
    assert v["top"] == "QL"
    # 裸 dict 前缀(测试态)→ 本地名缩写,与 render._c 口径一致
    assert v["violations"] == [
        {
            "axiom": "knows a SymmetricProperty",
            "bans": ["EL"],
            "subject": "http://example.org/m#knows",
        }
    ]


def test_transitive_stays_el() -> None:
    """EL 允许 transitive(禁的是 QL)→ top 仍是 EL."""
    text = RDFS_MINI + f":partOf a <{OWL}TransitiveProperty> .\n"
    v = classify(_mini(text), {})
    assert v["top"] == "EL"
    assert v["violations"] == []


def test_functional_object_property_flags_el_functional_datatype_not() -> None:
    """EL 只禁函数型对象属性;函数型数据属性留在 EL(但 QL 全禁 → RL)."""
    text = (
        RDFS_MINI
        + f":hasAge a <{OWL}DatatypeProperty>, <{OWL}FunctionalProperty> .\n"
        + ":hasParent a"
        f" <{OWL}ObjectProperty>, <{OWL}FunctionalProperty> .\n"
    )
    v = classify(_mini(text), {})
    # EL 挂(对象函数型)、QL 挂(词表级全禁函数型)→ RL
    assert v["top"] == "RL"
    el_hit = [x for x in v["violations"] if "EL" in x["bans"]]
    assert len(el_hit) == 1
    assert "hasParent" in el_hit[0]["axiom"]
    assert "hasAge" in " ".join(x["axiom"] for x in v["violations"])


def test_violations_capped_at_200() -> None:
    """205 条违规只报 200(violations 上限)."""
    lines = [RDFS_MINI] + [f":c{i} <{OWL}minCardinality> {i} ." for i in range(205)]
    v = classify(_mini("\n".join(lines)), {})
    assert v["top"] == "DL"
    assert len(v["violations"]) == 200
