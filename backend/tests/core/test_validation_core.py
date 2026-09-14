"""core/validation: 归一化、预设、AF 扫描、引擎真跑 (spec 2026-09-08 §2.2/§2.3)."""

import pyoxigraph as ox

from ontoworkbench.core.validation import (
    MAX_VALIDATION_RESULTS,
    PRESETS,
    PyrudofEngine,
    af_terms_in,
    normalize_report,
    run_validated,
)

REPORT_TTL = """\
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix ex: <http://example.org/> .
[] a sh:ValidationReport ;
    sh:conforms false ;
    sh:result [
        a sh:ValidationResult ;
        sh:severity sh:Violation ;
        sh:focusNode ex:Bob ;
        sh:resultPath ex:ssn ;
        sh:value "123" ;
        sh:resultMessage "两个 ssn" ;
        sh:sourceConstraintComponent sh:PatternConstraintComponent ;
    ] , [
        a sh:ValidationResult ;
        sh:severity sh:Warning ;
        sh:focusNode ex:Calvin ;
        sh:resultMessage "无 comment" ;
    ] .
"""

MINI = "/tmp/ow-validate-mini.ttl"  # setup 里写入的迷你本体


def _write_mini(tmp_path):
    data = (
        b"@prefix ex: <http://example.org/> .\n"
        b"ex:A a <http://www.w3.org/2002/07/owl#Class> ;"
        b'  <http://www.w3.org/2000/01/rdf-schema#label> "A"@en .\n'
    )
    p = tmp_path / "mini.ttl"
    p.write_bytes(data)
    return str(p)


def test_normalize_three_severities_and_curie() -> None:
    """Both severities counted, focus/path/constraint curie-ized via the table."""
    r = normalize_report(REPORT_TTL, {"ex": "http://example.org/"})
    assert r.conforms is False
    assert r.counts == {"violation": 1, "warning": 1, "info": 0}
    assert r.focus_count == 2
    first = r.results[0]
    assert first.focus_curie == "ex:Bob"
    assert first.path == "ex:ssn"
    assert first.constraint == "sh:PatternConstraintComponent"
    assert first.severity == "violation"


def test_normalize_drops_deprecated_focus_and_recomputes() -> None:
    """drop_focus_iris filters deprecated-focus results before the cap.

    counts/focus_count recompute and conforms flips true when no violation
    remains (the whole point of ignoring deprecated noise).
    """
    r = normalize_report(
        REPORT_TTL, {"ex": "http://example.org/"}, drop_focus_iris={"http://example.org/Bob"}
    )
    assert r.deprecated_filtered == 1
    assert r.counts == {"violation": 0, "warning": 1, "info": 0}
    assert r.focus_count == 1
    assert r.conforms is True
    assert all(i.focus_curie != "ex:Bob" for i in r.results)


def test_normalize_without_drop_keeps_engine_verdict() -> None:
    """No drop set: payload identical to M1 (deprecated_filtered=0, engine conforms)."""
    r = normalize_report(REPORT_TTL, {"ex": "http://example.org/"})
    assert r.deprecated_filtered == 0
    assert r.conforms is False and r.focus_count == 2
    assert r.counts == {"violation": 1, "warning": 1, "info": 0}


def test_normalize_caps_at_max_and_marks_truncated() -> None:
    """Results beyond the cap are dropped and flagged with truncated=True."""
    item = "[ a sh:ValidationResult ; sh:severity sh:Info ; sh:focusNode ex:N ] ,"
    big = REPORT_TTL.replace("sh:result [", f"sh:result {item * (MAX_VALIDATION_RESULTS + 1)} [", 1)
    r = normalize_report(big, {"ex": "http://example.org/"})
    assert len(r.results) == MAX_VALIDATION_RESULTS
    assert r.truncated is True


def test_presets_carry_four_rules_and_zh_messages() -> None:
    """Preset bodies carry the pinned rule knobs and Chinese messages, and parse."""
    obo = next(p for p in PRESETS if p.id == "obo-integrity")
    assert "sh:qualifiedMinCount 1" in obo.source
    assert "每类应至少有一个 rdfs:label" in obo.source
    assert "实例应至少有一个类型声明" in obo.source
    minimal = next(p for p in PRESETS if p.id == "minimal-label")
    assert "sh:minCount 1" in minimal.source
    for p in PRESETS:  # 预设必须本身是合法 Turtle
        ox.parse(p.source.encode(), format=ox.RdfFormat.TURTLE)


def test_af_terms_scan() -> None:
    """SPARQL-service vocabulary is flagged; plain sh shapes come back clean."""
    sparql_ttl = b"@prefix sh: <http://www.w3.org/ns/shacl#> . [] sh:sparql [ sh:select '''''' ] ."
    hits = af_terms_in(ox.parse(sparql_ttl, format=ox.RdfFormat.TURTLE))
    assert "sh:sparql" in hits
    clean_ttl = b"@prefix sh: <http://www.w3.org/ns/shacl#> . [] sh:targetClass sh:Shape ."
    clean = af_terms_in(ox.parse(clean_ttl, format=ox.RdfFormat.TURTLE))
    assert clean == []


def test_engine_end_to_end_on_mini(tmp_path) -> None:
    """Real pyrudof run: missing rdfs:comment surfaces as a warning result."""
    data_path = _write_mini(tmp_path)
    shapes = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "[] a sh:NodeShape ; sh:targetClass owl:Class ;\n"
        "   sh:property [ sh:path rdfs:comment ; sh:minCount 1 ; sh:severity sh:Warning ] .\n"
    )
    turtle, elapsed_ms = run_validated(PyrudofEngine(), data_path, shapes, "turtle", timeout_s=60.0)
    r = normalize_report(turtle, {})
    assert r.conforms is False and r.counts["warning"] == 1
    assert elapsed_ms >= 0
