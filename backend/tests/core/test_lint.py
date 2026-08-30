"""Structural lint rules: each rule gets a positive and a negative sample."""

from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.lint import RULES, run_rule
from ontoworkbench.core.parsing import parse_graph

TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class . ex:B a owl:Class ; owl:disjointWith ex:A .
ex:C a owl:Class ; rdfs:subClassOf ex:A , ex:B .
ex:D a owl:Class ; rdfs:subClassOf ex:A .
ex:i1 a owl:NamedIndividual , ex:A , ex:B .
ex:i2 a owl:NamedIndividual , ex:D .
"""


def _ir(src: str = TTL):
    return build_ir(parse_graph(src.encode(), "turtle"))


def test_disjoint_parents_flags_c() -> None:
    """C parents both A and B (disjoint); D parents only A."""
    res = run_rule("disjoint-parents", parse_graph(TTL.encode(), "turtle"), _ir())
    subs = {f.subject for f in res.findings}
    assert "http://example.org/C" in subs
    assert "http://example.org/D" not in subs


def test_instance_disjoint_flags_i1_not_i2() -> None:
    """i1 types into both sides of the disjoint pair; i2 stays clean."""
    res = run_rule("instance-disjoint", parse_graph(TTL.encode(), "turtle"), _ir())
    subs = {f.subject for f in res.findings}
    assert "http://example.org/i1" in subs
    assert "http://example.org/i2" not in subs


def test_subclass_cycle_detected() -> None:
    """A ← D ← A: every member of the loop is flagged."""
    cyclic = TTL + "ex:A rdfs:subClassOf ex:D .\n"  # A ← D ← A
    res = run_rule("subclass-cycle", parse_graph(cyclic.encode(), "turtle"), _ir(cyclic))
    subs = {f.subject for f in res.findings}
    assert {"http://example.org/A", "http://example.org/D"} <= subs


def test_builtin_rule_registry_covers_first_three() -> None:
    """The Task 16/17 config surface names rules by id; pin the first three."""
    assert {"disjoint-parents", "instance-disjoint", "subclass-cycle"} <= set(RULES)


R456_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Novel a owl:Class ; rdfs:label "novel" .
ex:Orphan a owl:Class .
ex:wrote a owl:ObjectProperty ; rdfs:domain ex:Novel ; rdfs:range ex:Novel .
ex:year a owl:DatatypeProperty ; rdfs:domain ex:Novel ; rdfs:range xsd:integer .
ex:GoodBook a owl:NamedIndividual , ex:Novel ; rdfs:label "gb" ;
  ex:wrote ex:BadBook ; ex:year "二〇〇八" .
ex:BadBook a owl:NamedIndividual ; rdfs:label "gb" .
"""


def test_domain_range_flags_object_and_data() -> None:
    """GoodBook breaks both branches of the range check.

    wrote→typeless BadBook (object out of range) and year "二〇〇八"
    against xsd:integer (data out of range).
    """
    g = parse_graph(R456_TTL.encode(), "turtle")
    res = run_rule("domain-range", g, _ir(R456_TTL))
    subs = {f.subject for f in res.findings}
    assert "http://example.org/GoodBook" in subs
    assert "http://example.org/BadBook" not in subs


def test_missing_label_and_orphan() -> None:
    """Orphan has no label and no wiring; Novel is labeled and instanced."""
    g = parse_graph(R456_TTL.encode(), "turtle")
    ir = _ir(R456_TTL)
    orphan = {f.subject for f in run_rule("orphan-class", g, ir).findings}
    assert "http://example.org/Orphan" in orphan
    assert "http://example.org/Novel" not in orphan
    labeled = {f.subject for f in run_rule("missing-label", g, ir).findings}
    assert "http://example.org/Orphan" in labeled
    assert "http://example.org/GoodBook" not in labeled
    # The Task 16/17 config surface names rules by id; pin the first three.
    assert {"disjoint-parents", "instance-disjoint", "subclass-cycle"} <= set(RULES)
