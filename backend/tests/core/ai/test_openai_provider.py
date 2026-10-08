"""OpenAI adapter against httpx.MockTransport: request shape + response/stream parsing."""

import asyncio
import json

import httpx
from httpx import MockTransport, Response

from ontoworkbench.core.ai.base import AiConfig
from ontoworkbench.core.ai.openai_provider import OpenAIProvider
from ontoworkbench.core.ai.types import ModelRequest, TextDelta

CFG = AiConfig(
    provider="openai", base_url="https://api.test/v1", api_key="sk-t", model="test-model"
)


def _provider(handler) -> OpenAIProvider:
    """A provider whose HTTP layer is a MockTransport handler."""
    return OpenAIProvider(CFG, http_client=httpx.AsyncClient(transport=MockTransport(handler)))


def test_complete_maps_tools_and_parses_tool_calls() -> None:
    """Request carries system/tools/model; response maps text, tool_calls, usage."""
    captured: dict = {}
    reply = {
        "choices": [
            {
                "message": {
                    "content": "hi",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "search", "arguments": '{"q": "go"}'},
                        }
                    ],
                }
            }
        ],
        "usage": {"prompt_tokens": 11, "completion_tokens": 3},
    }

    def handler(request: httpx.Request) -> Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return Response(200, json=reply)

    p = _provider(handler)
    req = ModelRequest(messages=[{"role": "user", "content": "q"}], system="sys")
    resp = asyncio.run(p.complete(req))
    assert captured["url"] == "https://api.test/v1/chat/completions"
    assert captured["body"]["model"] == "test-model"
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert resp.text == "hi" and resp.in_tokens == 11 and resp.out_tokens == 3


def test_complete_with_tool_defs() -> None:
    """Tools map to OpenAI function-tool JSON."""
    captured: dict = {}

    def handler(request: httpx.Request) -> Response:
        captured["body"] = json.loads(request.content.decode())
        return Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {}})

    from ontoworkbench.core.ai.types import ToolDef

    p = _provider(handler)
    req = ModelRequest(
        messages=[{"role": "user", "content": "q"}],
        tools=[ToolDef(name="search", description="d", input_schema={"type": "object"})],
    )
    resp = asyncio.run(p.complete(req))
    tools = captured["body"]["tools"]
    assert tools[0]["type"] == "function"
    assert tools[0]["function"] == {
        "name": "search",
        "description": "d",
        "parameters": {"type": "object"},
    }
    assert resp.tool_calls == []


def test_stream_accumulates_tool_call_fragments() -> None:
    """stream(): text deltas pass through; tool_call fragments reassemble by index."""
    chunks = [
        {"choices": [{"delta": {"role": "assistant", "content": "he"}}]},
        {"choices": [{"delta": {"content": "y"}}]},
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "type": "function",
                                "function": {"name": "search", "arguments": '{"q":'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ' "go"}'}}]}}
            ]
        },
        {"choices": [{"delta": {}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 4}},
    ]
    sse = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request: httpx.Request) -> Response:
        return Response(200, headers={"content-type": "text/event-stream"}, content=sse.encode())

    p = _provider(handler)
    events = asyncio.run(_collect(p, ModelRequest(messages=[{"role": "user", "content": "q"}])))
    kinds = [type(e).__name__ for e in events]
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "hey"
    calls = [e for e in events if type(e).__name__ == "ToolCall"]
    assert len(calls) == 1 and calls[0].name == "search" and calls[0].arguments == {"q": "go"}
    assert kinds[-2] == "UsageEvent" and kinds[-1] == "Done"
    usage = events[-2]
    assert (usage.in_tokens, usage.out_tokens) == (7, 4)


def test_tool_result_messages_map_with_ids() -> None:
    """Neutral assistant.tool_calls + tool replies become OpenAI wire shapes."""
    captured: dict = {}

    def handler(request: httpx.Request) -> Response:
        captured["body"] = json.loads(request.content.decode())
        return Response(200, json={"choices": [{"message": {"content": "done"}}], "usage": {}})

    from ontoworkbench.core.ai.types import ToolCall

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
    assert msgs[1]["tool_calls"][0]["function"]["name"] == "search"
    assert msgs[1]["tool_calls"][0]["id"]
    assert msgs[2] == {
        "role": "tool",
        "tool_call_id": msgs[1]["tool_calls"][0]["id"],
        "content": '{"items": []}',
    }


async def _collect(p: OpenAIProvider, req: ModelRequest) -> list:
    return [e async for e in p.stream(req)]
