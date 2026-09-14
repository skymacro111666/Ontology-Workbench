"""SHACL validation: pyrudof adapter, report normalization, presets.

spec 2026-09-08 §2.2/§2.3 — engine-agnostic surface: everything the API
layer touches is ValidationEngine + normalize_report; the concrete engine
is PyrudofEngine (spike report 2026-09-08: Core 98/98, GO 33s/300s).
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutTimeout
from typing import Protocol

import pyoxigraph as ox
from pydantic import BaseModel

from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.core.terms import RDF_TYPE, WELL_KNOWN_PREFIXES

SH = "http://www.w3.org/ns/shacl#"
MAX_VALIDATION_RESULTS = 1000
# SHACL-AF vocabulary pyrudof silently ignores (spike: 8/15 AF tests
# conform when they should violate) — surfaced to the user as a warning.
AF_PREDICATES = (SH + "sparql", SH + "targetSPARQL")
AF_TYPES = (SH + "SPARQLConstraint", SH + "SPARQLSelectValidator", SH + "SPARQLAskValidator")
_SEVERITY = {SH + "Violation": "violation", SH + "Warning": "warning", SH + "Info": "info"}
_SEVERITY_ORDER = {"violation": 0, "warning": 1, "info": 2}
# fmt → pyrudof.RDFFormat member name (pyrudof imports lazily, in validate).
_DATA_FORMATS = {"turtle": "Turtle", "rdfxml": "RdfXml", "jsonld": "JsonLd"}


class Preset(BaseModel):
    """A bundled shapes preset: stable id, display name, Turtle source."""

    id: str
    name: str
    source: str


PRESETS: list[Preset] = [
    Preset(
        id="obo-integrity",
        name="OBO 风格·完整性",
        source="""\
@base  <http://example.org/preset/> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<#ClassShape> a sh:NodeShape ;
    sh:targetClass owl:Class ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:severity sh:Violation ;
        sh:message "每类应至少有一个 rdfs:label" ;
    ] ;
    sh:property [
        sh:path rdfs:comment ;
        sh:minCount 1 ;
        sh:severity sh:Warning ;
        sh:message "类建议带有 rdfs:comment 说明" ;
    ] ;
    sh:property [
        sh:path rdfs:subClassOf ;
        sh:minCount 1 ;
        sh:severity sh:Info ;
        sh:message "类建议声明父类(孤立类提示)" ;
    ] .

<#IndividualShape> a sh:NodeShape ;
    sh:targetClass owl:NamedIndividual ;
    sh:property [
        sh:path rdf:type ;
        sh:qualifiedMinCount 1 ;
        sh:qualifiedValueShape [ sh:not [ sh:in ( owl:NamedIndividual owl:Thing ) ] ] ;
        sh:severity sh:Violation ;
        sh:message "实例应至少有一个类型声明(rdf:type)" ;
    ] .
""",
    ),
    Preset(
        id="minimal-label",
        name="最小检查·每类一个 label",
        source="""\
@base  <http://example.org/preset/> .
@prefix sh:   <http://www.w3.org/ns/shacl#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

<#ClassShape> a sh:NodeShape ;
    sh:targetClass owl:Class ;
    sh:property [
        sh:path rdfs:label ;
        sh:minCount 1 ;
        sh:severity sh:Violation ;
        sh:message "每类应至少有一个 rdfs:label" ;
    ] .
""",
    ),
]


class ValidationTimeout(Exception):
    """The engine outlived OW_VALIDATE_TIMEOUT_S (escape-hatch abort)."""


class EngineFailure(Exception):
    """The engine raised; str() carries the detail for the API layer."""


class ValidationEngine(Protocol):
    """Engine-agnostic surface the API layer programs against."""

    name: str

    def validate(self, data_path: str, shapes_path: str, fmt: str) -> str:
        """Run validation over the data file + shapes file; report text out."""


class PyrudofEngine:
    """rudof via its PyO3 bindings (spike 2026-09-08: API surface pinned)."""

    name = "pyrudof"

    def validate(self, data_path: str, shapes_path: str, fmt: str) -> str:
        """Run rudof over the data file + shapes file; report back as Turtle."""
        import pyrudof

        enum_name = _DATA_FORMATS.get(fmt)
        if enum_name is None:
            raise EngineFailure(f"unsupported data format '{fmt}'")
        try:
            r = pyrudof.Rudof(pyrudof.RudofConfig())
            r.read_data(input=data_path, format=getattr(pyrudof.RDFFormat, enum_name))
            r.read_shacl(input=shapes_path, format=pyrudof.ShaclFormat.Turtle)
            r.validate_shacl()
            out = r.serialize_shacl_validation_results(
                format=pyrudof.ResultShaclValidationFormat.Turtle
            )
        except Exception as exc:  # pyrudof.RudofError 等 — 统一给 API 层
            raise EngineFailure(str(exc)) from exc
        return out if isinstance(out, str) else out.decode("utf-8")


def run_validated(
    engine: ValidationEngine, data_path: str, shapes_source: str, fmt: str, timeout_s: float
) -> tuple[str, float]:
    """Run the engine behind the lint-style escape hatch.

    On timeout the worker thread is abandoned, not joined — a hung worker
    leaks, a recorded tradeoff.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".ttl", encoding="utf-8") as sf:
        sf.write(shapes_source)
        sf.flush()
        t0 = time.perf_counter()
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            future = ex.submit(engine.validate, data_path, sf.name, fmt)
            try:
                turtle = future.result(timeout=timeout_s)
            except FutTimeout as exc:
                raise ValidationTimeout(str(timeout_s)) from exc
            except EngineFailure:
                raise
            except Exception as exc:
                raise EngineFailure(str(exc)) from exc
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return turtle, (time.perf_counter() - t0) * 1000.0


class ValidationItem(BaseModel):
    """One sh:result, fully stringified; curie-ization already applied."""

    severity: str
    focus_iri: str | None = None
    focus_curie: str | None = None
    path: str | None = None
    constraint: str | None = None
    message: str | None = None
    value: str | None = None


class NormalizedReport(BaseModel):
    """The payload model behind the validation view (spec §2.3)."""

    conforms: bool
    focus_count: int
    counts: dict[str, int]
    results: list[ValidationItem]
    truncated: bool
    # M2「忽略已废弃」: results whose focus node is owl:deprecated, dropped
    # from the payload (0 when the filter is off / nothing matched).
    deprecated_filtered: int = 0


def af_terms_in(quads: Iterable[ox.Quad]) -> list[str]:
    """Which SHACL-AF terms the quads use (pyrudof ignores them silently).

    Takes any quad iterable — ox.parse(...) output or an ox.Store (store
    iteration yields quads too). AF types appear as rdf:type objects;
    predicate hits are the AF_PREDICATES scan.
    """
    names: set[str] = set()
    for q in quads:
        p = q.predicate.value
        o = q.object.value if isinstance(q.object, ox.NamedNode) else None
        for t in AF_PREDICATES:
            if p == t:
                names.add("sh:" + t[len(SH) :])
        for t in AF_TYPES:
            if o == t:
                names.add("sh:" + t[len(SH) :])
    return sorted(names)


def _term_str(term: object) -> str | None:
    if isinstance(term, (ox.NamedNode, ox.Literal)):
        return term.value
    return None


def normalize_report(
    report_turtle: str,
    prefixes: dict[str, str],
    cap: int = MAX_VALIDATION_RESULTS,
    drop_focus_iris: set[str] | None = None,
) -> NormalizedReport:
    """Engine RDF report → payload model (spec §2.3); curie via the ontology table.

    The table merges over the well-known prefixes plus sh: — reports quote
    sh:/rdfs:/owl: IRIs whatever the ontology declares; caller entries win.
    Severity is read from sh:resultSeverity (what pyrudof emits) or the
    shorthand sh:severity. Results are sorted severity-first (pyrudof's own
    order — the ox store shuffles it via random blank-node ids), then by
    focus/path, so the payload is deterministic.

    drop_focus_iris (M2 忽略已废弃) drops results whose focus node is in the
    set — before the cap, so the kept 1000 are post-filter — and recounts
    counts/focus_count. When anything was dropped, conforms is recomputed as
    "no violation remains" (the engine verdict reflects the unfiltered run).
    """
    store = ox.Store()
    store.load(bytes(report_turtle, "utf-8"), format=ox.RdfFormat.TURTLE)
    pm = PrefixMap.from_dict({**WELL_KNOWN_PREFIXES, "sh": SH, **prefixes})
    conforms = True
    conforms_pred = ox.NamedNode(SH + "conforms")
    for q in store.quads_for_pattern(None, conforms_pred, None, ox.DefaultGraph()):
        if isinstance(q.object, ox.Literal):
            conforms = q.object.value.lower() == "true"
    items: list[ValidationItem] = []
    focus_iris: set[str] = set()
    truncated = False
    drop = drop_focus_iris or ()
    deprecated_filtered = 0
    result_type = ox.NamedNode(SH + "ValidationResult")
    for q in store.quads_for_pattern(None, RDF_TYPE, result_type, ox.DefaultGraph()):
        if len(items) >= cap:
            truncated = True
            break
        node = q.subject
        severity: str = "violation"
        focus: str | None = None
        path: str | None = None
        constraint: str | None = None
        message: str | None = None
        value: str | None = None
        for attr in store.quads_for_pattern(node, None, None, ox.DefaultGraph()):
            pred = attr.predicate.value
            if pred in (SH + "resultSeverity", SH + "severity"):
                if isinstance(attr.object, ox.NamedNode):
                    severity = _SEVERITY.get(attr.object.value, "violation")
            elif pred == SH + "focusNode":
                focus = _term_str(attr.object)
            elif pred == SH + "resultPath":
                path = _term_str(attr.object)
            elif pred == SH + "sourceConstraintComponent":
                constraint = _term_str(attr.object)
            elif pred == SH + "resultMessage":
                message = _term_str(attr.object)
            elif pred == SH + "value":
                value = _term_str(attr.object)
        if focus is not None and focus in drop:
            deprecated_filtered += 1
            continue
        curie = None
        if focus:
            focus_iris.add(focus)
            got = pm.curie_for(focus)
            curie = f"{got[0]}:{got[1]}" if got else None
        items.append(
            ValidationItem(
                severity=severity,
                focus_iri=focus,
                focus_curie=curie,
                path=_curie_str(pm, path),
                constraint=_curie_str(pm, constraint),
                message=message,
                value=value,
            )
        )
    counts = {k: sum(1 for i in items if i.severity == k) for k in ("violation", "warning", "info")}
    if deprecated_filtered:
        conforms = conforms or not any(i.severity == "violation" for i in items)
    items.sort(
        key=lambda i: (
            _SEVERITY_ORDER.get(i.severity, 3),
            i.focus_iri or "",
            i.path or "",
            i.constraint or "",
            i.message or "",
        )
    )
    return NormalizedReport(
        conforms=conforms,
        focus_count=len(focus_iris),
        counts=counts,
        results=items,
        truncated=truncated,
        deprecated_filtered=deprecated_filtered,
    )


def _curie_str(pm: PrefixMap, uri: str | None) -> str | None:
    if uri is None:
        return None
    got = pm.curie_for(uri)
    return f"{got[0]}:{got[1]}" if got else uri
