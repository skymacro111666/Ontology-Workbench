"""Neutral request/response types shared by every ModelProvider adapter.

Message dicts (the only wire format the rest of the codebase sees):
  {"role": "user", "content": str}
  {"role": "assistant", "content": str}
  {"role": "assistant", "tool_calls": list[ToolCall]}
  {"role": "tool", "name": str, "content": str}
SDK-specific shapes (tool_call_id, content blocks) never leave an adapter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field


@dataclass(slots=True)
class ToolDef:
    """A tool offered to the model."""

    name: str
    description: str
    input_schema: dict


@dataclass(slots=True)
class ToolCall:
    """The model's request to call one tool."""

    name: str
    arguments: dict


@dataclass(slots=True)
class ModelRequest:
    """One completion request."""

    messages: list[dict]
    system: str | None = None
    tools: Sequence[ToolDef] = ()
    max_tokens: int = 4096


@dataclass(slots=True)
class ModelResponse:
    """One non-streamed completion result."""

    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    in_tokens: int = 0
    out_tokens: int = 0
    # Provider-native stop reason ("end_turn"/"stop", "max_tokens"/"length", …):
    # lets callers fail fast on truncation instead of parsing empty text.
    stop_reason: str | None = None


@dataclass(slots=True)
class TextDelta:
    """A streaming text increment."""

    text: str


@dataclass(slots=True)
class UsageEvent:
    """Final token usage of a streamed completion."""

    in_tokens: int
    out_tokens: int


@dataclass(slots=True)
class Done:
    """Terminal marker of a streamed completion."""


StreamEvent = TextDelta | ToolCall | UsageEvent | Done
