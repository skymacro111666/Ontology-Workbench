"""The chat assistant's read-only tool surface (spec-2 §3.1).

Seven tools, executed in-process over the same Indexes/store/lint/
validation implementations the MCP read tools wrap — no HTTP, no stdio.
Every executor returns a JSON string (ensure_ascii=False); failures are
`{"error": ...}` payloads, never raises, so one bad call cannot kill the
agent round.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import pyoxigraph as ox
from fastapi import Request

from ontoworkbench.core.ai.types import ToolDef
from ontoworkbench.core.indexes import Indexes
from ontoworkbench.core.lint import CustomRuleSpec
from ontoworkbench.core.lint import run as run_lint_engine
from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.db.models import Ontology
from ontoworkbench.db.repositories import LintRuleRepository
from ontoworkbench.server.routers.browse import _camel
from ontoworkbench.server.routers.query import _run_query

SPARQL_ROW_CAP = 200


@dataclass
class ChatToolContext:
    """Everything a tool executor needs; built once per SSE request."""

    request: Request
    row: Ontology
    ix: Indexes
    store: ox.Store
    prefixes: PrefixMap


def tool_defs() -> list[ToolDef]:
    """The seven read-only tools offered to the model."""
    return [
        ToolDef(
            name="search_entities",
            description=(
                "Case-insensitive substring search over localname/label/comment. "
                "Each hit carries the eid for get_entity and matched_field saying "
                "which field hit; refine q or raise limit when limitReached."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "q": {"type": "string"},
                    "kind": {"enum": ["class", "property", "individual"]},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["q"],
            },
        ),
        ToolDef(
            name="get_entity",
            description=(
                "Full detail for one class/property/individual by eid (from "
                "search_entities or get_class_tree): labels, Manchester-syntax "
                "axioms, and neighbors."
            ),
            input_schema={
                "type": "object",
                "properties": {"eid": {"type": "string"}},
                "required": ["eid"],
            },
        ),
        ToolDef(
            name="get_class_tree",
            description=(
                "One level of the class tree: roots when parent_eid is omitted, "
                "direct children otherwise. Walk lazily via parent_eid (nodes "
                "carry children_count) instead of fetching the whole tree."
            ),
            input_schema={
                "type": "object",
                "properties": {"parent_eid": {"type": "string"}},
            },
        ),
        ToolDef(
            name="get_ontology",
            description=(
                "Metadata for this ontology: title, filename, format, class/"
                "property/instance/axiom counts, and revision."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDef(
            name="sparql_query",
            description=(
                "Run a read-only SPARQL SELECT (engine-enforced). Results cap at "
                "200 rows; rowsTruncated marks the cut — refine the query then."
            ),
            input_schema={
                "type": "object",
                "properties": {"qs": {"type": "string"}},
                "required": ["qs"],
            },
        ),
        ToolDef(
            name="run_lint",
            description=(
                "Run the ontology lint checks (naming, annotation, deprecated "
                "usage) and return counts plus the findings list."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDef(
            name="run_validation",
            description=(
                "Run instance-level SHACL validation against the configured "
                "shapes. Without shapes configured, returns a note saying so."
            ),
            input_schema={"type": "object", "properties": {}},
        ),
    ]


def _dump(obj: Any) -> Any:
    """Pydantic model → camelCase dict; passthrough otherwise."""
    if hasattr(obj, "model_dump"):
        return _camel(obj.model_dump())
    return obj


def _search(args: dict, ctx: ChatToolContext) -> dict:
    limit = int(args.get("limit") or 20)
    kind = args.get("kind")
    hits = ctx.ix.search(str(args.get("q", "")), limit=limit, type_=kind)
    return {
        "items": [_dump(h) for h in hits],
        "limit": limit,
        "limitReached": len(hits) >= limit,
    }


def _get_entity(args: dict, ctx: ChatToolContext) -> dict:
    e = ctx.ix.entity(str(args.get("eid", "")))
    if e is None:
        return {"error": "entity not found"}
    return {"entity": _dump(e), "neighbors": ctx.ix.neighbors(str(args.get("eid", "")))}


def _get_class_tree(args: dict, ctx: ChatToolContext) -> list:
    parent = args.get("parent_eid")
    return [_dump(n) for n in ctx.ix.tree(parent)]


def _get_ontology(args: dict, ctx: ChatToolContext) -> dict:
    row = ctx.row
    return {
        "title": row.title,
        "filename": row.filename,
        "format": row.format,
        "classCount": row.class_count,
        "propertyCount": row.property_count,
        "instanceCount": row.instance_count,
        "axiomCount": row.axiom_count,
        "revision": row.revision,
    }


def _sparql(args: dict, ctx: ChatToolContext) -> dict:
    out = _run_query(str(args.get("qs", "")), ctx.store, ctx.prefixes)
    rows = out.get("rows", [])
    out["rows"] = rows[:SPARQL_ROW_CAP]
    out["rowCount"] = len(out["rows"])
    out["rowsTruncated"] = len(rows) > SPARQL_ROW_CAP
    return out


def _run_lint(args: dict, ctx: ChatToolContext) -> dict:
    from ontoworkbench.db.session import sessionmaker_or_fail

    with sessionmaker_or_fail()() as s:  # short-lived: tools run off-thread
        rule_rows = LintRuleRepository(s).list_for(ctx.row.id)
    disabled = {r.key for r in rule_rows if r.kind == "builtin" and r.key is not None}
    custom = [
        CustomRuleSpec(
            id=str(r.id), name=r.name or "", severity=r.severity or "info", sparql=r.sparql or ""
        )
        for r in rule_rows
        if r.kind == "custom" and r.enabled
    ]
    report = run_lint_engine(ctx.store, ctx.ix.ir, disabled, custom)
    return {
        "counts": report.counts,
        "findings": [_camel(r.model_dump()) for r in report.results[:50]],
    }


def _run_validation(args: dict, ctx: ChatToolContext) -> dict:
    from ontoworkbench.db.repositories import ValidationShapesRepository
    from ontoworkbench.db.session import sessionmaker_or_fail
    from ontoworkbench.server.routers.validation import (
        PyrudofEngine,
        normalize_report,
        run_validated,
    )

    with sessionmaker_or_fail()() as s:
        stored = ValidationShapesRepository(s).get(ctx.row.id)
    source = stored.source if stored else None
    if not source or not source.strip():
        return {"note": "no validation shapes configured"}
    timeout_s = ctx.request.app.state.settings.validate_timeout_s
    engine = PyrudofEngine()
    turtle, _elapsed = run_validated(
        engine, ctx.row.storage_path, source, ctx.row.format, timeout_s
    )
    report = normalize_report(turtle, ctx.ix.ir.prefixes, drop_focus_iris=None)
    return _camel(report.model_dump())


_EXECUTORS = {
    "search_entities": _search,
    "get_entity": _get_entity,
    "get_class_tree": _get_class_tree,
    "get_ontology": _get_ontology,
    "sparql_query": _sparql,
    "run_lint": _run_lint,
    "run_validation": _run_validation,
}


def execute_tool(name: str, args: dict, ctx: ChatToolContext) -> str:
    """Run one tool; JSON string out, `{"error": ...}` on any failure."""
    fn = _EXECUTORS.get(name)
    if fn is None:
        return json.dumps({"error": f"unknown tool {name}"}, ensure_ascii=False)
    try:
        return json.dumps(fn(args, ctx), ensure_ascii=False)
    except Exception as e:  # noqa: BLE001 - a failed call must not kill the round
        return json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}, ensure_ascii=False)


def clip_result(text: str, limit_bytes: int | None = None) -> str:
    """Byte-clip at a UTF-8 boundary; the note tells the model it saw a prefix."""
    if limit_bytes is None:
        limit_bytes = int(os.environ.get("AI_TOOL_RESULT_LIMIT_KB", "32")) * 1024
    data = text.encode("utf-8")
    if len(data) <= limit_bytes:
        return text
    return (
        data[:limit_bytes].decode("utf-8", errors="ignore")
        + "\n[结果已截断:请用更精确的查询缩小范围]"
    )
