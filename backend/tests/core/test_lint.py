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
    # The Task 16/17 config surface names rules by id; pin the first three.
    assert {"disjoint-parents", "instance-disjoint", "subclass-cycle"} <= set(RULES)
