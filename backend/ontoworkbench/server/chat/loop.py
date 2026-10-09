"""The chat agent loop (spec-2 §3): stream → tools → stream, with a round cap.

Neutral (event, payload) tuples out — wire serialization is the endpoint's
job. Blocking tool work runs via asyncio.to_thread so the event loop keeps
draining; provider/CoreError exceptions propagate to the endpoint.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.ai.types import ModelRequest, TextDelta, ToolCall, UsageEvent
from ontoworkbench.server.chat.tools import ChatToolContext, clip_result, execute_tool, tool_defs

_HISTORY_WINDOW = 40
_ROUNDS_CAP_NOTE = "(已达最大轮数,先给出当前结论;想继续深入请再提问)"


def _summary(name: str, result: str) -> str:
    """One line describing a tool result (footer of the collapsed row)."""
    flat = " ".join(result.split())
    return f"{name}: {flat[:120]}"


async def run_chat(
    provider: ModelProvider,
    system: str,
    history: list[dict],
    content: str,
    ctx: ChatToolContext,
    max_rounds: int | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    """Drive the model until a tool-free round; yield neutral events."""
    rounds = max_rounds or int(os.environ.get("AI_CHAT_MAX_ROUNDS", "16"))
    messages: list[dict] = [*history[-_HISTORY_WINDOW:], {"role": "user", "content": content}]
    in_tokens = 0
    out_tokens = 0
    started = time.perf_counter()

    for _ in range(rounds):
        round_text = ""
        calls: list[ToolCall] = []
        async for ev in provider.stream(
            ModelRequest(messages=messages, system=system, tools=tool_defs())
        ):
            if isinstance(ev, TextDelta):
                round_text += ev.text
                yield ("delta", {"text": ev.text})
            elif isinstance(ev, ToolCall):
                calls.append(ev)
            elif isinstance(ev, UsageEvent):
                in_tokens += ev.in_tokens
                out_tokens += ev.out_tokens
            # Done just ends the stream; the loop decides what happens next

        if not calls:
            if round_text:
                messages.append({"role": "assistant", "content": round_text})
            yield (
                "done",
                {"inTokens": in_tokens, "outTokens": out_tokens, "elapsedMs": _ms(started)},
            )
            return

        messages.append({"role": "assistant", "tool_calls": calls})
        for call in calls:
            yield (
                "tool_start",
                {
                    "name": call.name,
                    "argsSummary": str(call.arguments)[:200],
                },
            )
            result = await asyncio.to_thread(execute_tool, call.name, dict(call.arguments), ctx)
            clipped = clip_result(result)
            yield (
                "tool_end",
                {
                    "name": call.name,
                    "ok": '"error"' not in clipped[:80],
                    "summary": _summary(call.name, result),
                },
            )
            messages.append({"role": "tool", "name": call.name, "content": clipped})

    # Rounds exhausted: close with text in the loop's own voice, not an error.
    yield ("delta", {"text": _ROUNDS_CAP_NOTE})
    yield ("done", {"inTokens": in_tokens, "outTokens": out_tokens, "elapsedMs": _ms(started)})


def _ms(started: float) -> int:
    """Whole milliseconds since `started`."""
    return int((time.perf_counter() - started) * 1000)
