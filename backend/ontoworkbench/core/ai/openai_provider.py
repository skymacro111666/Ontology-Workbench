"""OpenAI-compatible adapter (AsyncOpenAI; loaded lazily via get_provider)."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import structlog
from openai import APIError, APITimeoutError, AsyncOpenAI

from ontoworkbench.core.ai.base import AiConfig, ModelProvider, http_timeout_s
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


class OpenAIProvider(ModelProvider):
    """chat.completions mapping; tool_call fragments accumulate by index."""

    def __init__(self, cfg: AiConfig, http_client: httpx.AsyncClient | None = None) -> None:
        """Build the async client; http_client exists for MockTransport tests."""
        kwargs: dict[str, Any] = {"api_key": cfg.api_key or "none", "timeout": http_timeout_s()}
        if cfg.base_url:
            kwargs["base_url"] = cfg.base_url
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._model = cfg.model
        self._client = AsyncOpenAI(**kwargs)

    def _messages(self, req: ModelRequest) -> list[dict]:
        """Neutral dicts → OpenAI wire shapes (synthesized positional tool_call ids)."""
        out: list[dict] = []
        if req.system:
            out.append({"role": "system", "content": req.system})
        open_ids: list[str] = []
        for m in req.messages:
            role = m.get("role")
            if role == "tool":
                call_id = open_ids.pop(0) if open_ids else "call_0"
                out.append({"role": "tool", "tool_call_id": call_id, "content": str(m["content"])})
            elif role == "assistant" and "tool_calls" in m:
                calls = []
                open_ids = []
                for i, c in enumerate(m["tool_calls"]):
                    cid = f"call_{i}"
                    open_ids.append(cid)
                    calls.append(
                        {
                            "id": cid,
                            "type": "function",
                            "function": {
                                "name": c.name,
                                "arguments": json.dumps(c.arguments, ensure_ascii=False),
                            },
                        }
                    )
                out.append(
                    {"role": "assistant", "content": m.get("content") or "", "tool_calls": calls}
                )
            else:
                out.append({"role": role or "user", "content": str(m.get("content", ""))})
        return out

    def _tools(self, req: ModelRequest) -> list[dict] | None:
        """ToolDef list → function-tool JSON, or None to omit the key."""
        if not req.tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                },
            }
            for t in req.tools
        ]

    async def complete(self, req: ModelRequest) -> ModelResponse:
        """One non-streamed completion."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(req),
            "max_tokens": req.max_tokens,
        }
        tools = self._tools(req)
        if tools:
            kwargs["tools"] = tools
        started = time.perf_counter()
        _log.info(
            "llm.request",
            provider="openai",
            model=self._model,
            messages=len(req.messages),
            chars=_req_chars(req),
            max_tokens=req.max_tokens,
            tools=len(req.tools),
        )
        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except (APIError, APITimeoutError) as e:
            _log.error(
                "llm.error",
                provider="openai",
                model=self._model,
                error=type(e).__name__,
                message=str(e)[:300],
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            raise _map_error(e) from e
        msg = resp.choices[0].message
        calls = [
            ToolCall(
                name=tc.function.name,
                arguments=_loads(tc.function.arguments),
            )
            for tc in (msg.tool_calls or [])
        ]
        usage = resp.usage
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        stop_reason = getattr(resp.choices[0], "finish_reason", None)
        _log.info(
            "llm.response",
            provider="openai",
            model=self._model,
            in_tokens=in_tok,
            out_tokens=out_tok,
            text_len=len(msg.content or ""),
            tool_calls=len(calls),
            stop_reason=stop_reason,
            duration_ms=round((time.perf_counter() - started) * 1000),
        )
        return ModelResponse(
            text=msg.content or "",
            tool_calls=calls,
            in_tokens=in_tok,
            out_tokens=out_tok,
            stop_reason=stop_reason,
        )

    async def stream(self, req: ModelRequest) -> AsyncIterator[StreamEvent]:
        """Streamed completion: deltas pass through, tool fragments reassemble."""
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": self._messages(req),
            "max_tokens": req.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        tools = self._tools(req)
        if tools:
            kwargs["tools"] = tools
        started = time.perf_counter()
        _log.info(
            "llm.request",
            provider="openai",
            model=self._model,
            messages=len(req.messages),
            chars=_req_chars(req),
            max_tokens=req.max_tokens,
            tools=len(req.tools),
            stream=True,
        )
        try:
            chunk_iter = await self._client.chat.completions.create(**kwargs)
        except (APIError, APITimeoutError) as e:
            _log.error(
                "llm.error",
                provider="openai",
                model=self._model,
                error=type(e).__name__,
                message=str(e)[:300],
                duration_ms=round((time.perf_counter() - started) * 1000),
            )
            raise _map_error(e) from e
        frags: dict[int, dict[str, str]] = {}
        usage: tuple[int, int] | None = None
        text_chars = 0
        async for chunk in chunk_iter:
            if getattr(chunk, "usage", None):
                usage = (
                    chunk.usage.prompt_tokens or 0,
                    chunk.usage.completion_tokens or 0,
                )
            for choice in chunk.choices or []:
                delta = choice.delta
                if delta is None:
                    continue
                if delta.content:
                    text_chars += len(delta.content)
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:
                    frag = frags.setdefault(tc.index, {"name": "", "args": ""})
                    if tc.function:
                        if tc.function.name:
                            frag["name"] += tc.function.name
                        if tc.function.arguments:
                            frag["args"] += tc.function.arguments
        _log.info(
            "llm.response",
            provider="openai",
            model=self._model,
            in_tokens=usage[0] if usage else 0,
            out_tokens=usage[1] if usage else 0,
            text_len=text_chars,
            tool_calls=len(frags),
            duration_ms=round((time.perf_counter() - started) * 1000),
            stream=True,
        )
        for i in sorted(frags):
            yield ToolCall(name=frags[i]["name"], arguments=_loads(frags[i]["args"]))
        if usage:
            yield UsageEvent(*usage)
        yield Done()


def _loads(raw: str | None) -> dict:
    """Parse tool arguments defensively: broken JSON degrades to a _raw passthrough."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        return {"_raw": raw}
    return parsed if isinstance(parsed, dict) else {"_raw": raw}
