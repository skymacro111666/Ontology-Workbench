"""Drafting pipeline orchestration (spec §5.3): batch loop → merge → TTL → guardrails."""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from pydantic import BaseModel, Field

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.ai.structured import complete_json
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse
from ontoworkbench.core.drafting.batching import plan_batches
from ontoworkbench.core.drafting.guard import run_guardrails
from ontoworkbench.core.drafting.merge import MergedDraft, merge_decisions, render_ttl
from ontoworkbench.core.drafting.models import DecisionSet, SchemaModel
from ontoworkbench.core.drafting.prompt import build_prompt
from ontoworkbench.core.errors import CoreError


class DraftResult(BaseModel):
    """Everything the generate endpoint returns (minus job plumbing)."""

    decisions: MergedDraft
    ttl: bytes
    lint_findings: list[dict] = Field(default_factory=list)
    stats: dict = Field(default_factory=dict)


def _env_int(name: str, default: int) -> int:
    """Read an AI_* knob with a sane fallback."""
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


async def generate_draft(
    provider: ModelProvider,
    schema: SchemaModel,
    namespace: str,
    label_language: str,
    batch_tables: int | None = None,
    max_tables: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> DraftResult:
    """Run the full drafting pipeline; progress(k, n) fires after each batch.

    should_cancel is polled at each batch top (the wizard's 放弃): raising
    between batches keeps every remaining LLM call unspent.
    """
    batch_tables = (
        batch_tables if batch_tables is not None else _env_int("AI_DRAFT_BATCH_TABLES", 35)
    )
    max_tables = max_tables if max_tables is not None else _env_int("AI_DRAFT_MAX_TABLES", 500)
    if len(schema.tables) > max_tables:
        raise CoreError(
            "VALIDATION_ERROR",
            f"schema has {len(schema.tables)} tables, limit {max_tables}",
            hint="deselect tables or raise AI_DRAFT_MAX_TABLES",
        )

    started = time.perf_counter()
    batches = plan_batches(schema.tables, batch_tables=batch_tables)
    all_names = [t.name for t in schema.tables]
    usage: list[ModelResponse] = []
    decisions: list[DecisionSet] = []
    for k, batch in enumerate(batches, start=1):
        if should_cancel is not None and should_cancel():
            raise CoreError("DRAFT_CANCELLED", "draft cancelled by user")
        batch_schema = SchemaModel(database_name=schema.database_name, tables=batch)
        prompt = build_prompt(batch_schema, all_names, namespace, label_language)
        decisions.append(
            await complete_json(
                provider,
                ModelRequest(
                    messages=[{"role": "user", "content": prompt}],
                    # Thinking models burn budget on reasoning before the JSON
                    # (GLM-5.3 needed >4096 just to think on a 20-table batch),
                    # so the output default is generous; env-tunable like the
                    # other drafting knobs.
                    max_tokens=_env_int("AI_DRAFT_MAX_TOKENS", 96384),
                ),
                DecisionSet,
                usage_sink=usage,
            )
        )
        if progress is not None:
            progress(k, len(batches))

    merged = merge_decisions(decisions, schema)
    ttl = render_ttl(
        merged,
        namespace=namespace,
        prefix=_prefix_for(schema.database_name),
        title=schema.database_name,
        label_language=label_language,
    )
    findings = run_guardrails(ttl)
    return DraftResult(
        decisions=merged,
        ttl=ttl,
        lint_findings=findings,
        stats={
            "classCount": len(merged.classes),
            "objectPropertyCount": len(merged.object_properties),
            "dataPropertyCount": len(merged.data_properties),
            "batchCount": len(batches),
            "inTokens": sum(r.in_tokens for r in usage),
            "outTokens": sum(r.out_tokens for r in usage),
            "elapsedMs": round((time.perf_counter() - started) * 1000, 1),
        },
    )


def _prefix_for(database_name: str) -> str:
    """A safe Turtle prefix from the database label (blank-create convention)."""
    slug = "".join(ch if ch.isalnum() else "_" for ch in database_name.lower()).strip("_")
    if not slug:
        slug = "db"
    if slug[0].isdigit():
        slug = f"o{slug}"
    return slug[:24]
