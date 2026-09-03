"""Structural lint rules: each rule gets a positive and a negative sample."""

from rdflib import Graph

from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.lint import RULES, run_rule
from ontoworkbench.core.parsing import parse_store

TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class . ex:B a owl:Class ; owl:disjointWith ex:A .
ex:C a owl:Class ; rdfs:subClassOf ex:A , ex:B .
ex:D a owl:Class ; rdfs:subClassOf ex:A .
ex:i1 a owl:NamedIndividual , ex:A , ex:B .
ex:i2 a owl:NamedIndividual , ex:D .
"""


def _graph(src: str) -> Graph:
    """The rdflib Graph the lint engine still walks (its migration is T12)."""
    return Graph().parse(data=src.encode(), format="turtle")


def _ir(src: str = TTL):
    return build_ir_store(*parse_store(src.encode(), "turtle"))


def test_disjoint_parents_flags_c() -> None:
    """C parents both A and B (disjoint); D parents only A."""
    res = run_rule("disjoint-parents", _graph(TTL), _ir())
    subs = {f.subject for f in res.findings}
    assert "http://example.org/C" in subs
    assert "http://example.org/D" not in subs


def test_instance_disjoint_flags_i1_not_i2() -> None:
    """i1 types into both sides of the disjoint pair; i2 stays clean."""
    res = run_rule("instance-disjoint", _graph(TTL), _ir())
    subs = {f.subject for f in res.findings}
    assert "http://example.org/i1" in subs
    assert "http://example.org/i2" not in subs


def test_subclass_cycle_detected() -> None:
    """A ← D ← A: every member of the loop is flagged."""
    cyclic = TTL + "ex:A rdfs:subClassOf ex:D .\n"  # A ← D ← A
    res = run_rule("subclass-cycle", _graph(cyclic), _ir(cyclic))
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
    g = _graph(R456_TTL)
    res = run_rule("domain-range", g, _ir(R456_TTL))
    subs = {f.subject for f in res.findings}
    assert "http://example.org/GoodBook" in subs
    assert "http://example.org/BadBook" not in subs


def test_missing_label_and_orphan() -> None:
    """Orphan has no label and no wiring; Novel is labeled and instanced."""
    g = _graph(R456_TTL)
    ir = _ir(R456_TTL)
    orphan = {f.subject for f in run_rule("orphan-class", g, ir).findings}
    assert "http://example.org/Orphan" in orphan
    assert "http://example.org/Novel" not in orphan
    labeled = {f.subject for f in run_rule("missing-label", g, ir).findings}
    assert "http://example.org/Orphan" in labeled
    assert "http://example.org/GoodBook" not in labeled


R789_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/> .
ex:Novel a owl:Class ; rdfs:subClassOf foaf:Document ; rdfs:label "n" .
ex:Lonely a owl:Class ; rdfs:label "n" .
ex:deadProp a owl:ObjectProperty .
ex:i1 a owl:NamedIndividual , ex:Novel ; rdfs:label "same" .
ex:i2 a owl:NamedIndividual , ex:Novel ; rdfs:label "same" .
"""


def test_unused_property_and_undeclared_ref() -> None:
    """Flag deadProp (no assertions, no wiring) and the undeclared parent.

    Novel's subClassOf points at the never-declared foaf:Document.
    """
    g, ir = _graph(R789_TTL), _ir(R789_TTL)
    assert "http://example.org/deadProp" in {
        f.subject for f in run_rule("unused-property", g, ir).findings
    }
    refs = {f.subject for f in run_rule("undeclared-ref", g, ir).findings}
    assert "http://example.org/Novel" in refs  # foaf:Document 未声明


def test_duplicate_label_groups() -> None:
    """i1/i2 share the label "same"; the group surfaces with its params."""
    g, ir = _graph(R789_TTL), _ir(R789_TTL)
    res = run_rule("duplicate-label", g, ir)
    assert any(f.params.get("label") == "same" for f in res.findings)


def test_custom_rule_rows_to_findings() -> None:
    """A SPARQL SELECT's rows land as findings under the spec's id."""
    from ontoworkbench.core.lint import CustomRuleSpec, run

    src = R456_TTL.replace('ex:year "二〇〇八"', 'ex:year "1937"^^xsd:integer')
    spec = CustomRuleSpec(
        id="c1",
        name="老书",
        severity="info",
        sparql="SELECT ?s WHERE { ?s <http://example.org/year> ?y . FILTER(?y < 1950) }",
    )
    g = _graph(src)
    report = run(g, _ir(src), disabled=set(), custom=[spec])
    custom = next(r for r in report.results if r.rule_id == "c1")
    assert custom.error is None
    assert "http://example.org/GoodBook" in {f.subject for f in custom.findings}


def test_custom_rule_timeout(monkeypatch) -> None:
    """A hung SPARQL query returns TIMEOUT instead of blocking the run."""
    import time as _time

    from rdflib import Graph as _Graph

    from ontoworkbench.core.lint import CustomRuleSpec, _run_custom

    def slow_query(self, q):
        _time.sleep(0.3)
        return []

    monkeypatch.setattr(_Graph, "query", slow_query)
    spec = CustomRuleSpec(id="c2", name="x", severity="info", sparql="SELECT ?s WHERE {}")
    res = _run_custom(spec, None, _Graph(), timeout_s=0.05)
    assert res.error == "TIMEOUT" and res.findings == []
    # The Task 16/17 config surface names rules by id; pin the first three.
    assert {"disjoint-parents", "instance-disjoint", "subclass-cycle"} <= set(RULES)
