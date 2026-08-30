"""Structural ontology lint (B3): pure (graph, ir) -> findings.

No reasoner — every rule is a hand-written linear-ish walk (spec §5/§9);
each rule caps at MAX_FINDINGS with a truthful pre-cap total.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pydantic import BaseModel
from rdflib import OWL, Graph
from rdflib.term import URIRef

from ontoworkbench.core.ir import IRBundle

MAX_FINDINGS = 200

XSD_NS = "http://www.w3.org/2001/XMLSchema#"


class Finding(BaseModel):
    """One rule hit: the offending entity plus params for the copy."""

    rule_id: str
    severity: str
    subject: str
    subject_curie: str
    params: dict[str, str] = {}


class RuleResult(BaseModel):
    """One rule's outcome: capped findings, truthful total, timing, error."""

    rule_id: str
    name: str | None = None  # custom rules carry their display name
    severity: str | None = None  # custom rules: error|warning|info
    duration_ms: float
    findings: list[Finding]
    total: int
    truncated: bool
    error: str | None = None  # TIMEOUT | SPARQL_ERROR: …


class LintReport(BaseModel):
    """The whole run's payload: per-rule results plus severity counts."""

    counts: dict[str, int]
    results: list[RuleResult]


@dataclass(frozen=True)
class RuleDef:
    """A builtin rule: id, default severity, and its (graph, ir) check."""

    rule_id: str
    severity: str
    check: Callable[[Graph, IRBundle], Iterable[tuple[str, dict[str, str]]]]


RULES: dict[str, RuleDef] = {}

# A rule check's shape: (graph, ir) -> (subject_eid, params) pairs.
CheckFn = Callable[[Graph, IRBundle], Iterable[tuple[str, dict[str, str]]]]


def rule(rule_id: str, severity: str) -> Callable[[CheckFn], CheckFn]:
    """Register a check under its id (the Task 16/17 config surface)."""

    def deco(fn: CheckFn) -> CheckFn:
        RULES[rule_id] = RuleDef(rule_id, severity, fn)
        return fn

    return deco


def _curie_of(ir: IRBundle, eid: str) -> str:
    e = ir.entities.get(eid)
    if e:
        return e.curie
    ind = ir.individuals.get(eid)
    # Custom SPARQL rules can surface subjects that are neither declared
    # entities nor collected individuals — fall back to the local name.
    return ind.curie if ind else eid.rsplit("/", 1)[-1].rsplit("#", 1)[-1]


def _ancestors_factory(ir: IRBundle) -> Callable[[str], set[str]]:
    """Memoized superclass closure (cycle-safe), shared by rules 2/4."""
    memo: dict[str, set[str]] = {}

    def closure(eid: str) -> set[str]:
        if eid in memo:
            return memo[eid]
        memo[eid] = {eid}  # cycle guard
        e = ir.entities.get(eid)
        out: set[str] = set()
        if e:
            out.add(eid)
            for p in e.parents:
                out |= closure(p.eid)
        memo[eid] = out
        return out

    return closure


def run_rule(rule_id: str, graph: Graph, ir: IRBundle) -> RuleResult:
    """Run one builtin rule with timing and the findings cap."""
    defn = RULES[rule_id]
    t0 = time.perf_counter()
    raw = list(defn.check(graph, ir))
    total = len(raw)
    findings = [
        Finding(
            rule_id=rule_id,
            severity=defn.severity,
            subject=eid,
            subject_curie=_curie_of(ir, eid),
            params=params,
        )
        for eid, params in raw[:MAX_FINDINGS]
    ]
    return RuleResult(
        rule_id=rule_id,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        findings=findings,
        total=total,
        truncated=total > MAX_FINDINGS,
    )


def _disjoint_pairs(graph: Graph) -> set[frozenset[str]]:
    """All owl:disjointWith class pairs as frozensets, one pass."""
    out: set[frozenset[str]] = set()
    for s, _, o in graph.triples((None, OWL.disjointWith, None)):
        if isinstance(s, URIRef) and isinstance(o, URIRef):
            out.add(frozenset((str(s), str(o))))
    return out


@rule("disjoint-parents", "error")
def _disjoint_parents(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag classes whose direct parents include a disjoint pair.

    The pizza ontology's CheeseyVegetableTopping pattern: unsatisfiable
    without any reasoning.
    """
    dis = _disjoint_pairs(graph)
    if not dis:
        return
    for e in ir.entities.values():
        if e.type != "Class":
            continue
        parents = e.parents
        for i, p1 in enumerate(parents):
            for p2 in parents[i + 1 :]:
                if frozenset((p1.eid, p2.eid)) in dis:
                    yield e.eid, {"parent1": p1.curie, "parent2": p2.curie}


@rule("instance-disjoint", "error")
def _instance_disjoint(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag instances whose type closure spans a disjoint pair.

    Direct types plus their superclasses; unsatisfiable without any
    reasoner.
    """
    dis = _disjoint_pairs(graph)
    if not dis:
        return
    closure = _ancestors_factory(ir)
    for ind in ir.individuals.values():
        types: set[str] = set()
        for c in ind.classes:
            types |= closure(c.eid)
        hit = next((pair for pair in dis if pair <= types), None)
        if hit is not None:
            a, b = sorted(hit)
            yield ind.eid, {"class1": _curie_of(ir, a), "class2": _curie_of(ir, b)}


@rule("subclass-cycle", "error")
def _subclass_cycle(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """SubClassOf cycles via iterative three-color DFS (GO-scale safe)."""
    children: dict[str, list[str]] = {}
    for e in ir.entities.values():
        if e.type == "Class":
            for p in e.parents:
                if p.eid in ir.entities:
                    children.setdefault(p.eid, []).append(e.eid)
    color: dict[str, int] = {}  # 1 gray / 2 black
    on_cycle: set[str] = set()
    for root in children:
        if color.get(root):
            continue
        color[root] = 1
        path = [root]
        stack = [iter(children.get(root, []))]
        while stack:
            advanced = False
            for nxt in stack[-1]:
                state = color.get(nxt, 0)
                if state == 0:
                    color[nxt] = 1
                    path.append(nxt)
                    stack.append(iter(children.get(nxt, [])))
                    advanced = True
                    break
                if state == 1:  # back edge: everything from nxt down the path cycles
                    on_cycle.update(path[path.index(nxt) :])
            if not advanced:
                color[path.pop()] = 2
                stack.pop()
    for eid in sorted(on_cycle):
        yield eid, {}


def _range_index(ir: IRBundle) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """Map property eid → declared class ranges / xsd datatype ranges."""
    rng_classes: dict[str, list[str]] = {}
    rng_dts: dict[str, list[str]] = {}
    for e in ir.entities.values():
        if e.type == "Class":
            continue
        for r in e.referenced_by:
            if r.relation != "rdfs:range" or not r.eid:
                continue
            if r.eid.startswith(XSD_NS):
                rng_dts.setdefault(e.eid, []).append(r.eid)
            else:
                rng_classes.setdefault(e.eid, []).append(r.eid)
    return rng_classes, rng_dts


@rule("domain-range", "error")
def _domain_range(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag assertions outside the property's declared range.

    Object assertion values whose type closure misses every declared class
    range; data assertions whose literal fails the declared xsd range.
    """
    from ontoworkbench.core.parsing import literal_type_ok

    rng_classes, rng_dts = _range_index(ir)
    closure = _ancestors_factory(ir)
    for ind in ir.individuals.values():
        for a in ind.object_assertions:
            want = rng_classes.get(a.property.eid)
            if not want:
                continue
            target = ir.individuals.get(a.object.eid)
            ttypes: set[str] = set()
            if target:
                for c in target.classes:
                    ttypes |= closure(c.eid)
            if not any(w in ttypes for w in want):
                yield ind.eid, {"property": a.property.curie, "value": a.object.curie}
        for da in ind.data_assertions:
            for dt in rng_dts.get(da.property.eid, []):
                if not literal_type_ok(da.value, dt):
                    yield (
                        ind.eid,
                        {
                            "property": da.property.curie,
                            "value": da.value,
                            "expected": dt.rsplit("#", 1)[-1],
                        },
                    )


@rule("missing-label", "warning")
def _missing_label(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag declared entities and individuals with no rdfs:label at all."""
    for e in ir.entities.values():
        if not e.label:
            yield e.eid, {}
    for ind in ir.individuals.values():
        if not ind.label:
            yield ind.eid, {}


@rule("orphan-class", "warning")
def _orphan_class(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag classes with no parents, children, instances or domain/range wiring."""
    for e in ir.entities.values():
        if e.type != "Class":
            continue
        if e.parents or e.children or e.stats.direct_children:
            continue
        if ir.instances.get(e.eid):
            continue
        wired = any(r.relation != "subClassOf" for r in e.referenced_by)
        if not wired:
            yield e.eid, {}


@rule("unused-property", "warning")
def _unused_property(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag declared properties with no assertions anywhere and no domain/range."""
    used: set[str] = set()
    for ind in ir.individuals.values():
        for oa in ind.object_assertions:
            used.add(oa.property.eid)
        for da in ind.data_assertions:
            used.add(da.property.eid)
    for e in ir.entities.values():
        if e.type == "Class" or e.eid in used:
            continue
        wired = any(r.relation in ("rdfs:domain", "rdfs:range") for r in e.referenced_by)
        if not wired:
            yield e.eid, {}


@rule("undeclared-ref", "info")
def _undeclared_ref(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag external IRIs used as parents / ranges / assertion values.

    Legal vocabulary reuse — informational only.
    """
    for e in ir.entities.values():
        for p in e.parents:
            if p.eid not in ir.entities:
                yield e.eid, {"ref": p.curie}
        for r in e.referenced_by:
            if r.relation == "rdfs:range" and r.eid and r.eid not in ir.entities:
                if not r.eid.startswith(XSD_NS):
                    yield e.eid, {"ref": r.curie}
    for ind in ir.individuals.values():
        for oa in ind.object_assertions:
            if oa.object.eid not in ir.individuals and oa.object.eid not in ir.entities:
                yield ind.eid, {"ref": oa.object.curie}


@rule("duplicate-label", "info")
def _duplicate_label(graph: Graph, ir: IRBundle) -> Iterable[tuple[str, dict[str, str]]]:
    """Flag the same (lang, value) label shared by several entities/individuals."""
    groups: dict[tuple[str, str], list[str]] = {}
    for coll in (ir.entities.values(), ir.individuals.values()):
        for item in coll:
            for lang, value in item.label.items():
                groups.setdefault((lang, value), []).append(item.eid)
    for (lang, value), eids in sorted(groups.items()):
        if len(eids) > 1:
            yield sorted(eids)[0], {"label": value, "lang": lang, "count": str(len(eids))}


class CustomRuleSpec(BaseModel):
    """A user-authored SPARQL rule (from lint config's custom rows)."""

    id: str
    name: str
    severity: str
    sparql: str


def _run_custom(
    spec: CustomRuleSpec, ir: IRBundle | None, graph: Graph, timeout_s: float = 10.0
) -> RuleResult:
    """Run one custom SPARQL SELECT with a hard timeout.

    rdflib has no query timeout, so an executor we refuse to join is the
    escape hatch (a hung worker leaks until it eventually finishes —
    recorded tradeoff).
    """
    from concurrent.futures import ThreadPoolExecutor
    from concurrent.futures import TimeoutError as FutTimeout

    t0 = time.perf_counter()

    def _query() -> list:
        return list(graph.query(spec.sparql))

    try:
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            rows = ex.submit(_query).result(timeout=timeout_s)
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
    except FutTimeout:
        return RuleResult(
            rule_id=spec.id,
            name=spec.name,
            severity=spec.severity,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            findings=[],
            total=0,
            truncated=False,
            error="TIMEOUT",
        )
    except Exception as exc:  # syntax errors etc. — a finding, not a crash
        return RuleResult(
            rule_id=spec.id,
            name=spec.name,
            severity=spec.severity,
            duration_ms=round((time.perf_counter() - t0) * 1000, 1),
            findings=[],
            total=0,
            truncated=False,
            error=f"SPARQL_ERROR: {exc}",
        )
    findings = []
    for row in rows[:MAX_FINDINGS]:
        terms = list(row)
        subject = str(terms[0]) if terms else ""
        findings.append(
            Finding(
                rule_id=spec.id,
                severity=spec.severity,
                subject=subject,
                subject_curie=_curie_of(ir, subject) if ir else subject.rsplit("/", 1)[-1],
                params={f"v{i}": str(t) for i, t in enumerate(terms[1:], start=1)},
            )
        )
    return RuleResult(
        rule_id=spec.id,
        name=spec.name,
        severity=spec.severity,
        duration_ms=round((time.perf_counter() - t0) * 1000, 1),
        findings=findings,
        total=len(rows),
        truncated=len(rows) > MAX_FINDINGS,
    )


def run(
    graph: Graph,
    ir: IRBundle,
    disabled: set[str],
    custom: list[CustomRuleSpec],
    only_rule_id: str | None = None,
    timeout_s: float = 10.0,
) -> LintReport:
    """Assemble the full report: enabled builtins + enabled custom rules."""
    results: list[RuleResult] = []
    for defn in RULES.values():
        if only_rule_id and defn.rule_id != only_rule_id:
            continue
        if defn.rule_id in disabled:
            continue
        results.append(run_rule(defn.rule_id, graph, ir))
    for spec in custom:
        if only_rule_id and spec.id != only_rule_id:
            continue
        results.append(_run_custom(spec, ir, graph, timeout_s))
    counts = {"error": 0, "warning": 0, "info": 0}
    for r in results:
        for f in r.findings:
            counts[f.severity] = counts.get(f.severity, 0) + 1
    return LintReport(counts=counts, results=results)
