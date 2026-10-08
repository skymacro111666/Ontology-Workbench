"""Guardrail chain (spec §5.3 step 4): syntax gate → IR → lint.

The draft never reaches a human (or the DB) without passing the same
deterministic checks an upload would.
"""

from __future__ import annotations

from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.lint import run as run_lint_engine
from ontoworkbench.core.parsing import timed_parse_store


def run_guardrails(ttl: bytes) -> list[dict]:
    """Parse, build IR, run the full lint set; return findings as dicts.

    Raises CoreError PARSE_FAILED from the parser on invalid Turtle — the
    same error an upload with this content would produce.
    """
    store, prefixes, _ = timed_parse_store(ttl, "turtle")
    ir = build_ir_store(store, prefixes)
    report = run_lint_engine(store, ir, disabled=set(), custom=[])
    return [r.model_dump() for r in report.results]
