"""Structural lint rules: each rule gets a positive and a negative sample."""

import pyoxigraph as ox

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


def _store(src: str) -> ox.Store:
    """Parse turtle into the Store the lint engine walks."""
    return parse_store(src.encode(), "turtle")[0]


def _ir(src: str = TTL):
    return build_ir_store(*parse_store(src.encode(), "turtle"))


def test_disjoint_parents_flags_c() -> None:
    """C parents both A and B (disjoint); D parents only A."""
    res = run_rule("disjoint-parents", _store(TTL), _ir())
    subs = {f.subject for f in res.findings}
    assert "http://example.org/C" in subs
    assert "http://example.org/D" not in subs


def test_instance_disjoint_flags_i1_not_i2() -> None:
    """i1 types into both sides of the disjoint pair; i2 stays clean."""
    res = run_rule("instance-disjoint", _store(TTL), _ir())
    subs = {f.subject for f in res.findings}
    assert "http://example.org/i1" in subs
    assert "http://example.org/i2" not in subs


def test_subclass_cycle_detected() -> None:
    """A ← D ← A: every member of the loop is flagged."""
    cyclic = TTL + "ex:A rdfs:subClassOf ex:D .\n"  # A ← D ← A
    res = run_rule("subclass-cycle", _store(cyclic), _ir(cyclic))
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
    res = run_rule("domain-range", _store(R456_TTL), _ir(R456_TTL))
    subs = {f.subject for f in res.findings}
    assert "http://example.org/GoodBook" in subs
    assert "http://example.org/BadBook" not in subs


def test_missing_label_and_orphan() -> None:
    """Orphan has no label and no wiring; Novel is labeled and instanced."""
    store, ir = _store(R456_TTL), _ir(R456_TTL)
    orphan = {f.subject for f in run_rule("orphan-class", store, ir).findings}
    assert "http://example.org/Orphan" in orphan
    assert "http://example.org/Novel" not in orphan
    labeled = {f.subject for f in run_rule("missing-label", store, ir).findings}
    assert "http://example.org/Orphan" in labeled
    assert "http://example.org/GoodBook" not in labeled


VERSION_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:ont a owl:Ontology .
ex:A a owl:Class .
"""


def test_missing_version_warns_when_absent() -> None:
    """No owl:versionInfo anywhere → one warning on the ontology IRI."""
    res = run_rule("missing-version", _store(VERSION_TTL), _ir(VERSION_TTL))
    assert [(f.subject, f.severity) for f in res.findings] == [
        ("http://example.org/ont", "warning")
    ]


def test_missing_version_silent_when_present() -> None:
    """A versionInfo on the header satisfies the release discipline."""
    tagged = VERSION_TTL.replace(
        "ex:ont a owl:Ontology .", 'ex:ont a owl:Ontology ; owl:versionInfo "1.0.0" .'
    )
    res = run_rule("missing-version", _store(tagged), _ir(tagged))
    assert res.findings == [] and res.total == 0


def test_missing_version_falls_back_without_header() -> None:
    """No owl:Ontology declaration either → finding still fires, subject ''."""
    res = run_rule("missing-version", _store(TTL), _ir(TTL))
    assert [f.subject for f in res.findings] == [""]


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
    store, ir = _store(R789_TTL), _ir(R789_TTL)
    assert "http://example.org/deadProp" in {
        f.subject for f in run_rule("unused-property", store, ir).findings
    }
    refs = {f.subject for f in run_rule("undeclared-ref", store, ir).findings}
    assert "http://example.org/Novel" in refs  # foaf:Document 未声明


def test_duplicate_label_groups() -> None:
    """i1/i2 share the label "same"; the group surfaces with its params."""
    res = run_rule("duplicate-label", _store(R789_TTL), _ir(R789_TTL))
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
    report = run(_store(src), _ir(src), disabled=set(), custom=[spec])
    custom = next(r for r in report.results if r.rule_id == "c1")
    assert custom.error is None
    assert "http://example.org/GoodBook" in {f.subject for f in custom.findings}


def test_custom_rule_timeout(monkeypatch) -> None:
    """A hung SPARQL query returns TIMEOUT instead of blocking the run."""
    import time as _time

    import pyoxigraph as _ox

    from ontoworkbench.core.lint import CustomRuleSpec, _run_custom

    def slow_query(self, q):
        _time.sleep(0.3)
        return []

    monkeypatch.setattr(_ox.Store, "query", slow_query)
    spec = CustomRuleSpec(id="c2", name="x", severity="info", sparql="SELECT ?s WHERE {}")
    res = _run_custom(spec, None, _ox.Store(), timeout_s=0.05)
    assert res.error == "TIMEOUT" and res.findings == []
    # The Task 16/17 config surface names rules by id; pin the first three.
    assert {"disjoint-parents", "instance-disjoint", "subclass-cycle"} <= set(RULES)


# --- T1 batch (OntoBricks/D2KLab checklist, 2026-10-06) ---------------------

CLOSURE_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:X a owl:Class . ex:Y a owl:Class ; owl:disjointWith ex:X .
ex:A a owl:Class ; rdfs:subClassOf ex:X .
ex:B a owl:Class ; rdfs:subClassOf ex:Y .
ex:C a owl:Class ; rdfs:subClassOf ex:A , ex:B .
ex:G a owl:Class ; rdfs:subClassOf ex:H ; owl:disjointWith ex:H .
ex:H a owl:Class .
ex:Clean a owl:Class ; rdfs:subClassOf ex:A .
"""


def test_disjoint_parents_closure_flags_p11_and_p13() -> None:
    """Closure clashes: P1.3 via ancestors, P1.1 declared with own parent."""
    res = run_rule("disjoint-parents", _store(CLOSURE_TTL), _ir(CLOSURE_TTL))
    subs = {f.subject for f in res.findings}
    assert "http://example.org/C" in subs  # via closure (P1.3)
    assert "http://example.org/G" in subs  # declared disjoint with own parent (P1.1)
    assert "http://example.org/Clean" not in subs
    assert "http://example.org/H" not in subs  # H itself stays satisfiable


REDUNDANT_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class . ex:B a owl:Class ; rdfs:subClassOf ex:A .
ex:C a owl:Class ; rdfs:subClassOf ex:A , ex:B .
ex:D a owl:Class ; rdfs:subClassOf ex:B .
"""


def test_redundant_subclass_flags_direct_parent_reachable_via_sibling() -> None:
    """P1.2: C declares ⊑A directly but A is already implied via B."""
    res = run_rule("redundant-subclass", _store(REDUNDANT_TTL), _ir(REDUNDANT_TTL))
    subs = {f.subject for f in res.findings}
    assert subs == {"http://example.org/C"}
    assert res.findings[0].params["via"] == "ex:B"


SUBPROP_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Root a owl:Class . ex:Leaf a owl:Class ; rdfs:subClassOf ex:Root .
ex:Elsewhere a owl:Class .
ex:p a owl:ObjectProperty ; rdfs:domain ex:Root ; rdfs:range xsd:string .
ex:sBad a owl:ObjectProperty ; rdfs:subPropertyOf ex:p ; rdfs:domain ex:Elsewhere .
ex:sOk a owl:ObjectProperty ; rdfs:subPropertyOf ex:p ; rdfs:domain ex:Leaf .
ex:sSame a owl:ObjectProperty ; rdfs:subPropertyOf ex:p ; rdfs:range xsd:string .
"""


def test_subproperty_expansion_flags_broader_domain_not_narrower() -> None:
    """P2.5: broadening flagged; narrowing and exact datatype stay clean."""
    res = run_rule("subproperty-expansion", _store(SUBPROP_TTL), _ir(SUBPROP_TTL))
    subs = {f.subject for f in res.findings}
    assert subs == {"http://example.org/sBad"}
    assert res.findings[0].params["side"] == "domain"


SHADOW_TTL = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:label a owl:ObjectProperty .
ex:seeAlso a owl:DatatypeProperty .
ex:hasTopping a owl:ObjectProperty ; rdfs:label "topping"@en .
ex:describedBy a owl:ObjectProperty ; rdfs:label "comment"@en .
ex:named a owl:Class ; rdfs:label "comment"@en .
"""


def test_shadow_vocabulary_flags_standard_term_collisions() -> None:
    """P3.1: local names (and labels) colliding with rdf/rdfs/owl terms."""
    res = run_rule("shadow-vocabulary", _store(SHADOW_TTL), _ir(SHADOW_TTL))
    subs = {f.subject for f in res.findings}
    assert "http://example.org/label" in subs
    assert "http://example.org/seeAlso" in subs
    assert "http://example.org/describedBy" in subs  # collision via its label
    assert "http://example.org/hasTopping" not in subs  # label "topping" is no term
    assert "http://example.org/named" not in subs  # classes are not the subject here
