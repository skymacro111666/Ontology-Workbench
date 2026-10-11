"""Anthropic adapter against httpx.MockTransport: request shape + response/stream parsing."""

import asyncio
import json

import httpx2
import pytest
from httpx2 import MockTransport, Response

from ontoworkbench.core.ai.anthropic_provider import AnthropicProvider
from ontoworkbench.core.ai.base import AiConfig
from ontoworkbench.core.ai.types import ModelRequest, TextDelta, ToolCall, ToolDef

CFG = AiConfig(
    provider="anthropic", base_url="https://api.test", api_key="ak-t", model="test-model"
)

TOOLS = [ToolDef(name="search", description="d", input_schema={"type": "object"})]


def _provider(handler) -> AnthropicProvider:
    """A provider whose HTTP layer is a MockTransport handler."""
    return AnthropicProvider(CFG, http_client=httpx2.AsyncClient(transport=MockTransport(handler)))


def _sse(events: list[dict]) -> bytes:
    """Anthropic wire frames: event name + JSON data per frame."""
    out = []
    for ev in events:
        out.append(f"event: {ev.pop('event', 'unknown')}\n")
        out.append(f"data: {json.dumps(ev)}\n\n")
    return "".join(out).encode()


def test_complete_maps_tools_and_parses_tool_use() -> None:
    """Request carries top-level system/input_schema; response maps blocks + usage."""
    captured: dict = {}
    reply = {
        "content": [
            {"type": "text", "text": "hi"},
            {"type": "tool_use", "id": "t1", "name": "search", "input": {"q": "go"}},
        ],
        "usage": {"input_tokens": 11, "output_tokens": 3},
    }

    def handler(request: httpx2.Request) -> Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return Response(200, json=reply)

    p = _provider(handler)
    req = ModelRequest(messages=[{"role": "user", "content": "q"}], system="sys", tools=TOOLS)
    resp = asyncio.run(p.complete(req))
    assert captured["url"] == "https://api.test/v1/messages"
    body = captured["body"]
    assert body["model"] == "test-model" and body["system"] == "sys"
    assert body["tools"] == [
        {"name": "search", "description": "d", "input_schema": {"type": "object"}}
    ]
    assert resp.text == "hi"
    assert resp.tool_calls == [ToolCall(name="search", arguments={"q": "go"})]


def test_complete_surfaces_stop_reason_and_logs_roundtrip() -> None:
    """stop_reason rides along, and every call logs a diagnosis trail.

    llm.request + llm.response carry tokens/stop_reason for truncation detection.
    """
    from structlog.testing import capture_logs

    reply = {
        "content": [{"type": "thinking", "thinking": "long reasoning"}],
        "stop_reason": "max_tokens",
        "usage": {"input_tokens": 8722, "output_tokens": 4096},
    }
    p = _provider(lambda request: Response(200, json=reply))
    with capture_logs() as logs:
        resp = asyncio.run(p.complete(ModelRequest(messages=[{"role": "user", "content": "q"}])))
    assert resp.stop_reason == "max_tokens"
    assert resp.text == ""  # thinking blocks contribute no text
    events = {(e["event"], e.get("log_level")) for e in logs}
    assert ("llm.request", "info") in events
    assert ("llm.response", "info") in events
    resp_log = next(e for e in logs if e["event"] == "llm.response")
    assert resp_log["in_tokens"] == 8722 and resp_log["out_tokens"] == 4096
    assert resp_log["stop_reason"] == "max_tokens" and resp_log["model"] == "test-model"


def test_tool_result_messages_map_to_tool_result_blocks() -> None:
    """Neutral assistant.tool_calls + tool replies become tool_result user blocks."""
    captured: dict = {}

    def handler(request: httpx2.Request) -> Response:
        captured["body"] = json.loads(request.content.decode())
        return Response(
            200,
            json={
                "content": [{"type": "text", "text": "done"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    p = _provider(handler)
    req = ModelRequest(
        messages=[
            {"role": "user", "content": "q"},
            {"role": "assistant", "tool_calls": [ToolCall(name="search", arguments={"q": "go"})]},
            {"role": "tool", "name": "search", "content": '{"items": []}'},
        ]
    )
    asyncio.run(p.complete(req))
    msgs = captured["body"]["messages"]
    assert msgs[1]["role"] == "assistant"
    assert msgs[1]["content"][0]["type"] == "tool_use"
    assert msgs[1]["content"][0]["name"] == "search"
    assert msgs[2]["role"] == "user"
    assert msgs[2]["content"][0]["type"] == "tool_result"
    assert msgs[2]["content"][0]["tool_use_id"] == msgs[1]["content"][0]["id"]
    assert msgs[2]["content"][0]["content"] == '{"items": []}'


def test_stream_accumulates_input_json_deltas() -> None:
    """stream(): text deltas pass through; input_json_delta reassembles per block."""
    events = [
        {"event": "message_start", "type": "message_start", "message": {"usage": {}}},
        {
            "event": "content_block_start",
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "event": "content_block_delta",
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "he"},
        },
        {
            "event": "content_block_delta",
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "y"},
        },
        {"event": "content_block_stop", "type": "content_block_stop", "index": 0},
        {
            "event": "content_block_start",
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "t1", "name": "search", "input": {}},
        },
        {
            "event": "content_block_delta",
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
        },
        {
            "event": "content_block_delta",
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": ' "go"}'},
        },
        {"event": "content_block_stop", "type": "content_block_stop", "index": 1},
        {
            "event": "message_delta",
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"input_tokens": 7, "output_tokens": 4},
        },
        {"event": "message_stop", "type": "message_stop"},
    ]

    def handler(request: httpx2.Request) -> Response:
        return Response(200, headers={"content-type": "text/event-stream"}, content=_sse(events))

    p = _provider(handler)
    collected = asyncio.run(_collect(p, ModelRequest(messages=[{"role": "user", "content": "q"}])))
    kinds = [type(e).__name__ for e in collected]
    assert "".join(e.text for e in collected if isinstance(e, TextDelta)) == "hey"
    calls = [e for e in collected if isinstance(e, ToolCall)]
    assert len(calls) == 1 and calls[0].name == "search" and calls[0].arguments == {"q": "go"}
    assert kinds[-2] == "UsageEvent" and kinds[-1] == "Done"
    usage = collected[-2]
    assert (usage.in_tokens, usage.out_tokens) == (7, 4)


async def _collect(p: AnthropicProvider, req: ModelRequest) -> list:
    return [e async for e in p.stream(req)]


def test_http_timeout_env_tunable(monkeypatch: pytest.MonkeyPatch) -> None:
    """AI_HTTP_TIMEOUT_S feeds the SDK client timeout (default 900).

    Thinking models legitimately generate for minutes on large drafting
    batches; the old fixed 120s died three attempts in a row (10-11).
    """
    import anthropic

    monkeypatch.delenv("AI_HTTP_TIMEOUT_S", raising=False)
    p = _provider(lambda r: Response(200, json={"content": [], "usage": {}}))
    assert isinstance(p._client, anthropic.AsyncAnthropic)
    assert p._client.timeout == 900.0
    monkeypatch.setenv("AI_HTTP_TIMEOUT_S", "12.5")
    p2 = _provider(lambda r: Response(200, json={"content": [], "usage": {}}))
    assert p2._client.timeout == 12.5
