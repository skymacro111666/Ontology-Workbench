"""Vendor-neutral structured output (spec §1.4).

Prompt template → parse → pydantic → one retry carrying the validation
error → CoreError.
"""

from __future__ import annotations

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse
from ontoworkbench.core.errors import CoreError

T = TypeVar("T", bound=BaseModel)


def parse_json_block(text: str) -> dict:
    """Extract the outermost JSON object, tolerating ```json fences."""
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if t.count("```") >= 2 else t[3:]
        if t.startswith("json"):
            t = t[4:]
        t = t.strip()
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(t[start : end + 1])


async def complete_json(
    provider: ModelProvider,
    req: ModelRequest,
    schema: type[T],
    retries: int = 1,
    usage_sink: list[ModelResponse] | None = None,
) -> T:
    """Complete and validate against a pydantic schema, retrying once.

    usage_sink (when given) collects every raw ModelResponse so the caller
    (drafting pipeline) can sum token usage across batches.
    """
    messages = list(req.messages)
    last_err = ""
    for _ in range(retries + 1):
        resp = await provider.complete(
            ModelRequest(messages=messages, system=req.system, tools=(), max_tokens=req.max_tokens)
        )
        if usage_sink is not None:
            usage_sink.append(resp)
        # A stop at the token cap means the budget died mid-generation (often
        # inside a thinking model's reasoning phase, leaving zero text) —
        # retrying under the same cap re-burns the same budget, so fail fast
        # with the actionable error instead.
        if resp.stop_reason in ("max_tokens", "length"):
            raise CoreError(
                "LLM_OUTPUT_TRUNCATED",
                "model output hit the max_tokens cap before usable text",
                hint=(
                    "raise the output budget (AI_DRAFT_MAX_TOKENS for drafting) "
                    "or reduce the number of tables per run"
                ),
            )
        try:
            return schema.model_validate(parse_json_block(resp.text))
        except (ValueError, ValidationError) as e:
            last_err = str(e)[:2000]
            messages = messages + [
                {"role": "assistant", "content": resp.text},
                {
                    "role": "user",
                    "content": (
                        f"Your output was invalid: {last_err}\n"
                        "Return ONLY the corrected JSON object."
                    ),
                },
            ]
    raise CoreError(
        "LLM_OUTPUT_INVALID", "LLM output failed schema validation after retry", hint=last_err[:500]
    )
