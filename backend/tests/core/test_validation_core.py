"""core/validation: 归一化、预设、AF 扫描、引擎真跑 (spec 2026-09-08 §2.2/§2.3)."""

import pyoxigraph as ox

from ontoworkbench.core.validation import (
    MAX_VALIDATION_RESULTS,
    PRESETS,
    PyrudofEngine,
    ReportCache,
    ReportEntry,
    ValidationItem,
    af_terms_in,
    normalize_report,
    report_to_csv,
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
    assert r.total_results == MAX_VALIDATION_RESULTS + 3  # 全量计数:2 原有 + N+1 追加


def test_normalize_total_is_post_filter_universe() -> None:
    """total_results counts the kept universe (== export rows under the same filter).

    Drops past the cap still count into deprecated_filtered.
    """
    item = "[ a sh:ValidationResult ; sh:severity sh:Info ; sh:focusNode ex:Old ] ,"
    big = REPORT_TTL.replace("sh:result [", f"sh:result {item * 4} [", 1)
    r = normalize_report(
        big,
        {"ex": "http://example.org/"},
        cap=3,
        drop_focus_iris={"http://example.org/Old"},
    )
    assert r.deprecated_filtered == 4  # cap 外的丢弃也计入
    assert r.total_results == 2  # Bob + Calvin
    assert len(r.results) == 2 and r.truncated is False


def test_normalize_uncapped_returns_everything() -> None:
    """cap=None (export path): every kept result materializes."""
    item = "[ a sh:ValidationResult ; sh:severity sh:Info ; sh:focusNode ex:N ] ,"
    big = REPORT_TTL.replace("sh:result [", f"sh:result {item * 4} [", 1)
    r = normalize_report(big, {"ex": "http://example.org/"}, cap=None)
    assert len(r.results) == 6
    assert r.truncated is False and r.total_results == 6


def test_report_cache_lru_eviction() -> None:
    """Oldest entry evicts at capacity; a get() touch rescues the recent one."""
    c = ReportCache(max_entries=2)

    def _e(t: str) -> ReportEntry:
        return ReportEntry(
            revision=1, file_hash="f", shapes_hash="h", turtle=t, engine="pyrudof", elapsed_ms=1.0
        )

    c.put("o1", _e("t1"))
    c.put("o2", _e("t2"))
    assert c.get("o1") is not None and c.get("o1").turtle == "t1"  # touch o1
    c.put("o3", _e("t3"))  # evicts o2 (least recently used)
    assert c.get("o2") is None
    assert c.get("o1") is not None and c.get("o3") is not None


def test_report_csv_bom_header_and_quoting() -> None:
    """CSV carries the BOM (Excel + Chinese), the pinned header, csv quoting.

    Messages with commas/quotes come out csv-standard quoted.
    """
    rep = normalize_report(REPORT_TTL, {"ex": "http://example.org/"})
    rep = rep.model_copy(
        update={
            "results": [
                ValidationItem(
                    severity="warning",
                    focus_iri="http://example.org/A",
                    focus_curie="ex:A",
                    message='带,逗号 "引号" 消息',
                )
            ]
        }
    )
    text = report_to_csv(rep)
    assert text.startswith("﻿")
    lines = text.splitlines()
    assert lines[0] == "﻿severity,focus_iri,focus_curie,path,constraint,message,value"
    assert len(lines) == 2
    assert '"带,逗号 ""引号"" 消息"' in lines[1]


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
