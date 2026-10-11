"""complete_json: fence tolerance, one retry with error feedback, hard fail."""

import asyncio

import pytest
from pydantic import BaseModel

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.structured import complete_json, parse_json_block
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse
from ontoworkbench.core.errors import CoreError


class Decisions(BaseModel):
    """Minimal decision schema for the test."""

    classes: list[str]


REQ = ModelRequest(messages=[{"role": "user", "content": "draft"}])


def test_parse_json_block_tolerates_fences() -> None:
    """Fenced, fenced-with-language, and trailing-prose JSON all parse."""
    assert parse_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_block('```\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_block('Here you go: {"a": 1} hope that helps') == {"a": 1}


def test_fenced_json_parses() -> None:
    """The happy path: model wraps its JSON in a code fence."""
    p = FakeProvider([ModelResponse(text='```json\n{"classes": ["A"]}\n```')])
    out = asyncio.run(complete_json(p, REQ, Decisions))
    assert out.classes == ["A"]


def test_invalid_then_valid_retries_once() -> None:
    """First output violates the schema; the retry carries the corrected JSON."""
    p = FakeProvider(
        [ModelResponse(text='{"classes": [1, 2]}'), ModelResponse(text='{"classes": ["A"]}')]
    )
    out = asyncio.run(complete_json(p, REQ, Decisions))
    assert out.classes == ["A"]


def test_second_failure_raises_core_error() -> None:
    """Persistent garbage becomes LLM_OUTPUT_INVALID with the error as hint."""
    p = FakeProvider([ModelResponse(text="nope"), ModelResponse(text="still nope")])
    with pytest.raises(CoreError) as ei:
        asyncio.run(complete_json(p, REQ, Decisions))
    assert ei.value.code == "LLM_OUTPUT_INVALID"


def test_usage_sink_collects_raw_responses() -> None:
    """The sink sees every raw response, including the rejected first try."""
    sink: list[ModelResponse] = []
    p = FakeProvider(
        [
            ModelResponse(text='{"classes": [1]}', in_tokens=2, out_tokens=3),
            ModelResponse(text='{"classes": ["A"]}', in_tokens=4, out_tokens=5),
        ]
    )
    asyncio.run(complete_json(p, REQ, Decisions, usage_sink=sink))
    assert [r.in_tokens for r in sink] == [2, 4]


class _Counting(FakeProvider):
    """Counts complete() calls to prove fail-fast (no retry)."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        super().__init__(responses)
        self.calls = 0

    async def complete(self, req: ModelRequest) -> ModelResponse:
        self.calls += 1
        return await super().complete(req)


def test_truncated_output_fails_fast_without_retry() -> None:
    """A stop_reason at the token cap raises LLM_OUTPUT_TRUNCATED immediately.

    Retrying under the same cap re-burns the same budget (GLM-5.3 spent all
    4096 on thinking and emitted zero text) — fail fast with the actionable
    error instead.
    """
    p = _Counting([ModelResponse(text="", stop_reason="max_tokens")])
    with pytest.raises(CoreError) as ei:
        asyncio.run(complete_json(p, REQ, Decisions))
    assert ei.value.code == "LLM_OUTPUT_TRUNCATED"
    assert p.calls == 1


def test_truncated_openai_finish_reason_also_fails_fast() -> None:
    """The OpenAI dialect's finish_reason="length" is the same condition."""
    p = _Counting([ModelResponse(text='{"classes": ["par', stop_reason="length")])
    with pytest.raises(CoreError) as ei:
        asyncio.run(complete_json(p, REQ, Decisions))
    assert ei.value.code == "LLM_OUTPUT_TRUNCATED"
    assert p.calls == 1
