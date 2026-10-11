"""Anthropic adapter (AsyncAnthropic; loaded lazily via get_provider)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx2
import structlog
from anthropic import APIError, APITimeoutError, AsyncAnthropic

from ontoworkbench.core.ai.base import AiConfig, ModelProvider
from ontoworkbench.core.ai.types import (
    Done,
    ModelRequest,
    ModelResponse,
    StreamEvent,
    TextDelta,
    ToolCall,
    UsageEvent,
)
from ontoworkbench.core.errors import CoreError

_TIMEOUT_S = 120.0


def _map_error(e: Exception) -> CoreError:
    """Translate SDK exceptions into envelope codes (AI_TIMEOUT / AI_REQUEST_FAILED)."""
    if isinstance(e, APITimeoutError):
        return CoreError("AI_TIMEOUT", "model request timed out")
    if isinstance(e, APIError):
        return CoreError("AI_REQUEST_FAILED", f"provider request failed: {e}", hint=str(e)[:500])
    raise e


# Every call/response leaves a log trail: sizes and tokens only, never content.
_log = structlog.get_logger("ow.llm")


def _req_chars(req: ModelRequest) -> int:
    """Rough request payload size for the log line."""
    return sum(len(str(m.get("content", ""))) for m in req.messages) + len(req.system or "")


class AnthropicProvider(ModelProvider):
    """messages API mapping; tool_use blocks and input_json_delta accumulate."""

    def __init__(self, cfg: AiConfig, http_client: httpx2.AsyncClient | None = None) -> None:
        """Build the async client; http_client exists for MockTransport tests."""
        kwargs: dict[str, Any] = {"api_key": cfg.api_key or "none", "timeout": _TIMEOUT_S}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._model = cfg.model
        self._client = AsyncAnthropic(**kwargs)

    def _messages(self, req: ModelRequest) -> list[dict]:
        """Neutral dicts → Anthropic wire shapes.

        Assistant tool_calls turn into tool_use content blocks with synthesized
        positional ids; each following tool reply becomes its own user turn
        carrying one tool_result block (the API's required shape).
        """
        out: list[dict] = []
        open_ids: list[str] = []
        for m in req.messages:
            role = m.get("role")
            if role == "tool":
                tool_use_id = open_ids.pop(0) if open_ids else "toolu_0"
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_use_id,
                                "content": str(m["content"]),
                            }
                        ],
                    }
                )
            elif role == "assistant" and "tool_calls" in m:
                blocks: list[dict] = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": str(m["content"])})
                open_ids = []
                for i, c in enumerate(m["tool_calls"]):
                    tid = f"toolu_{i}"
                    open_ids.append(tid)
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tid,
                            "name": c.name,
                            "input": c.arguments,
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append(
                    {
                        "role": role or "user",
                        "content": [{"type": "text", "text": str(m.get("content", ""))}],
                    }
                )
        return out

    def _tools(self, req: ModelRequest) -> list[dict] | None:
        """ToolDef list → Anthropic tool JSON, or None to omit the key."""
        if not req.tools:
            return None
        return [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in req.tools
        ]

    async def complete(self, req: ModelRequest) -> ModelResponse:
        """One non-streamed completion."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(req),
            "max_tokens": req.max_tokens,
        }
        if req.system:
            kwargs["system"] = req.system
        tools = self._tools(req)
        if tools:
            kwargs["tools"] = tools
        started = time.perf_counter()
        _log.info(
            "llm.request",
            provider="anthropic",
            model=self._model,
            messages=len(req.messages),
            chars=_req_chars(req),
            max_tokens=req.max_tokens,
            tools=len(req.tools),
        )
        try:
            resp = await self._client.messages.create(**kwargs)
        except (APIError, APITimeoutError) as e:
            _log.error(
                "llm.error",
                provider="anthropic",
                model=self._model,
                error=type(e).__name__,
                message=str(e)[:300],
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            raise _map_error(e) from e
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                calls.append(ToolCall(name=block.name, arguments=dict(block.input or {})))
        in_tok = resp.usage.input_tokens if resp.usage else 0
        out_tok = resp.usage.output_tokens if resp.usage else 0
        _log.info(
            "llm.response",
            provider="anthropic",
            model=self._model,
            in_tokens=in_tok,
            out_tokens=out_tok,
            text_len=len("".join(text_parts)),
            tool_calls=len(calls),
            stop_reason=resp.stop_reason,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return ModelResponse(
            text="".join(text_parts),
            tool_calls=calls,
            in_tokens=in_tok,
            out_tokens=out_tok,
            stop_reason=resp.stop_reason,
        )

    async def stream(self, req: ModelRequest) -> AsyncIterator[StreamEvent]:
        """Streamed completion: text deltas pass through, input_json reassembles."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(req),
            "max_tokens": req.max_tokens,
        }
        if req.system:
            kwargs["system"] = req.system
        tools = self._tools(req)
        if tools:
            kwargs["tools"] = tools
        started = time.perf_counter()
        _log.info(
            "llm.request",
            provider="anthropic",
            model=self._model,
            messages=len(req.messages),
            chars=_req_chars(req),
            max_tokens=req.max_tokens,
            tools=len(req.tools),
            stream=True,
        )
        try:
            event_iter = await self._client.messages.create(stream=True, **kwargs)
        except (APIError, APITimeoutError) as e:
            _log.error(
                "llm.error",
                provider="anthropic",
                model=self._model,
                error=type(e).__name__,
                message=str(e)[:300],
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            raise _map_error(e) from e
        # Per-block accumulation: index → the open block; tool blocks collect
        # partial_json fragments until content_block_stop closes them.
        open_block: dict | None = None
        json_buf = ""
        usage: tuple[int, int] | None = None
        text_chars = 0
        tool_calls = 0
        async for ev in event_iter:
            etype = ev.type
            if etype == "content_block_start":
                open_block = dict(ev.content_block.model_dump(exclude_none=True))
                open_block["index"] = ev.index
                json_buf = ""
            elif etype == "content_block_delta":
                delta = ev.delta
                if delta.type == "text_delta":
                    text_chars += len(delta.text)
                    yield TextDelta(delta.text)
                elif delta.type == "input_json_delta":
                    json_buf += delta.partial_json
            elif etype == "content_block_stop":
                if open_block and open_block.get("type") == "tool_use":
                    tool_calls += 1
                    try:
                        args = json.loads(json_buf) if json_buf.strip() else {}
                    except ValueError:
                        args = {"_raw": json_buf}
                    yield ToolCall(name=open_block.get("name", ""), arguments=dict(args))
                open_block = None
                json_buf = ""
            elif etype == "message_delta":
                if getattr(ev, "usage", None):
                    usage = (ev.usage.input_tokens or 0, ev.usage.output_tokens or 0)
            elif etype == "message_start":
                msg = getattr(ev, "message", None)
                if msg is not None and getattr(msg, "usage", None):
                    usage = (msg.usage.input_tokens or 0, msg.usage.output_tokens or 0) or usage
        _log.info(
            "llm.response",
            provider="anthropic",
            model=self._model,
            in_tokens=usage[0] if usage else 0,
            out_tokens=usage[1] if usage else 0,
            text_len=text_chars,
            tool_calls=tool_calls,
            duration_ms=round((time.perf_counter() - started) * 1000),
            stream=True,
        )
        if usage:
            yield UsageEvent(*usage)
        yield Done()
