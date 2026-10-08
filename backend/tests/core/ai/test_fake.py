"""FakeProvider: scripted responses, identical pop order for both modes."""

import asyncio

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse, ToolCall

REQ = ModelRequest(messages=[{"role": "user", "content": "x"}])


async def _collect(p: FakeProvider, req: ModelRequest) -> list:
    return [e async for e in p.stream(req)]


def test_complete_pops_in_order() -> None:
    """complete() consumes the scripted list front to back."""
    p = FakeProvider([ModelResponse(text="a"), ModelResponse(text="b")])
    assert asyncio.run(p.complete(REQ)).text == "a"
    assert asyncio.run(p.complete(REQ)).text == "b"


def test_exhausted_raises() -> None:
    """Running out of script is a test bug, not a fallback."""
    p = FakeProvider([])
    try:
        asyncio.run(p.complete(REQ))
    except RuntimeError as e:
        assert "exhausted" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_stream_event_order() -> None:
    """stream(): TextDelta chunks, then whole ToolCalls, then Usage, then Done."""
    call = ToolCall(name="search_entities", arguments={"q": "go"})
    p = FakeProvider(
        [ModelResponse(text="hello world, streamed", tool_calls=[call], in_tokens=3, out_tokens=5)]
    )
    events = asyncio.run(_collect(p, ModelRequest(messages=[])))
    kinds = [type(e).__name__ for e in events]
    assert kinds[0] == "TextDelta" and kinds[-2] == "UsageEvent" and kinds[-1] == "Done"
    assert kinds.index("ToolCall") > kinds.index("TextDelta")
    assert "".join(e.text for e in events if type(e).__name__ == "TextDelta") == (
        "hello world, streamed"
    )
    usage = events[-2]
    assert (usage.in_tokens, usage.out_tokens) == (3, 5)
