"""Agent loop: event order, tool feedback, round cap (FakeProvider)."""

import asyncio
import json

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse, ToolCall
from ontoworkbench.server.chat import loop as loop_module
from ontoworkbench.server.chat.loop import run_chat


class Capturing(FakeProvider):
    """FakeProvider that records every ModelRequest it serves."""

    def __init__(self, responses: list[ModelResponse]) -> None:
        """Record requests while serving the scripted responses."""
        super().__init__(responses)
        self.seen: list[ModelRequest] = []

    async def stream(self, req: ModelRequest):
        """Record, then replay the scripted stream."""
        self.seen.append(req)
        async for ev in super().stream(req):
            yield ev


def _collect(provider, small_ctx, max_rounds: int | None = None):
    """Run the loop to completion synchronously."""

    async def run():
        events = []
        async for ev, payload in run_chat(
            provider, "system prompt", [], "介绍一下", small_ctx, max_rounds=max_rounds
        ):
            events.append((ev, payload))
        return events

    return asyncio.run(run())


def test_full_sequence_text_tools_final(small_ctx) -> None:
    """Round 1 calls two tools, round 2 streams the final text + done stats."""
    calls = [
        ToolCall(name="search_entities", arguments={"q": "Cust"}),
        ToolCall(name="get_class_tree", arguments={}),
    ]
    p = Capturing(
        [
            ModelResponse(text="", tool_calls=calls),
            ModelResponse(text="这个本体有客户和订单两个核心类。", in_tokens=100, out_tokens=20),
        ]
    )
    events = _collect(p, small_ctx)
    names = [n for n, _ in events]

    assert names[:4] == ["tool_start", "tool_end", "tool_start", "tool_end"]
    assert names[-1] == "done" and "delta" in names
    done = events[-1][1]
    assert done["inTokens"] == 100 and done["outTokens"] == 20
    assert done["elapsedMs"] >= 0
    tool_ends = [payload for n, payload in events if n == "tool_end"]
    assert all(isinstance(t["ok"], bool) and t["ok"] for t in tool_ends)
    assert all("summary" in t and "argsSummary" not in t for t in tool_ends)

    # the tool round fed back: round 2's request carries the tool history
    second = p.seen[1]
    tail_roles = [m.get("role") for m in second.messages]
    assert "tool" in tail_roles
    assert any(r == "assistant" for r in tail_roles)
    tool_rows = [m for m in second.messages if m.get("role") == "tool"]
    assert len(tool_rows) == 2
    assert "ex:Customer" in str(tool_rows[0]["content"])  # real result landed


def test_rounds_cap_ends_with_text(small_ctx) -> None:
    """Exhausted rounds end in the loop's own text + done, never an error."""
    call = ToolCall(name="get_ontology", arguments={})
    p = FakeProvider([ModelResponse(text="", tool_calls=[call]) for _ in range(20)])
    events = _collect(p, small_ctx, max_rounds=3)
    names = [n for n, _ in events]

    assert names[-1] == "done"
    assert not any(n == "error" for n in names)
    text = "".join(payload["text"] for n, payload in events if n == "delta")
    assert "轮" in text  # the cap note in the loop's own voice


def test_tool_ok_means_execution_not_findings(small_ctx, monkeypatch) -> None:
    """ok=False only for top-level error payloads.

    A lint report whose counts mention "error" findings is still a successful
    tool run.
    """
    lint_shaped = json.dumps(
        {"counts": {"error": 0, "warning": 3, "info": 1}, "findings": []}, ensure_ascii=False
    )
    monkeypatch.setattr(loop_module, "execute_tool", lambda name, args, ctx: lint_shaped)
    p = FakeProvider(
        [
            ModelResponse(text="", tool_calls=[ToolCall(name="run_lint", arguments={})]),
            ModelResponse(text="lint 完成。"),
        ]
    )
    events = _collect(p, small_ctx)
    tool_end = next(payload for n, payload in events if n == "tool_end")
    assert tool_end["name"] == "run_lint"
    assert tool_end["ok"] is True
