"""ModelProvider ABC + AI_* env config (no OW_ prefix by spec §1.3)."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass

from ontoworkbench.core.ai.types import ModelRequest, ModelResponse, StreamEvent


@dataclass(frozen=True, slots=True)
class AiConfig:
    """Effective provider config; DB settings override these env defaults."""

    provider: str  # "openai" (OpenAI-compatible) | "anthropic"
    base_url: str | None
    api_key: str
    model: str

    @property
    def configured(self) -> bool:
        """True when a model name and key are present."""
        return bool(self.api_key and self.model)

    @classmethod
    def from_env(cls) -> AiConfig:
        """Read the four AI_* variables; openai-compatible is the default family."""
        return cls(
            provider=os.environ.get("AI_MODEL_PROVIDER", "openai").strip().lower() or "openai",
            base_url=(os.environ.get("AI_BASE_URL") or "").strip() or None,
            api_key=(os.environ.get("AI_API_KEY") or "").strip(),
            model=(os.environ.get("AI_MODEL") or "").strip(),
        )


def http_timeout_s() -> float:
    """HTTP timeout for provider clients, in seconds (AI_HTTP_TIMEOUT_S).

    Thinking models legitimately generate for minutes on large drafting
    batches; the old fixed 120s died three attempts in a row (10-11 GLM-5.3
    incident: 3 × 120s + backoff = the observed 362s failure).
    """
    return float(os.getenv("AI_HTTP_TIMEOUT_S", "900"))


class ModelProvider(ABC):
    """Protocol-neutral LLM interface; adapters own all SDK differences."""

    @abstractmethod
    async def complete(self, req: ModelRequest) -> ModelResponse:
        """Non-streamed completion (drafting)."""

    @abstractmethod
    def stream(self, req: ModelRequest) -> AsyncIterator[StreamEvent]:
        """Streamed completion (chat): TextDelta* → ToolCall* → UsageEvent → Done."""
