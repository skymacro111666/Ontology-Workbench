"""LLM provider abstraction (SDKs are core dependencies; they load lazily)."""

from __future__ import annotations

from typing import Any

from ontoworkbench.core.ai.base import AiConfig, ModelProvider
from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.types import (
    Done,
    ModelRequest,
    ModelResponse,
    StreamEvent,
    TextDelta,
    ToolCall,
    ToolDef,
    UsageEvent,
)
from ontoworkbench.core.errors import CoreError

__all__ = [
    "AiConfig",
    "ModelProvider",
    "FakeProvider",
    "get_provider",
    "ModelRequest",
    "ModelResponse",
    "StreamEvent",
    "TextDelta",
    "ToolCall",
    "ToolDef",
    "UsageEvent",
    "Done",
]

_INSTALL_HINT = "the SDK ships with ontology-workbench; reinstall the package (uv sync)"


def get_provider(cfg: AiConfig, http_client: Any | None = None) -> ModelProvider:
    """Build the adapter for the configured protocol family.

    The SDK modules import lazily here so a bare `import ontoworkbench.core.ai`
    stays cheap; only provider construction can touch the SDK, and a broken
    install fails as AI_NOT_CONFIGURED with the reinstall hint.
    """
    if cfg.provider == "anthropic":
        try:
            from ontoworkbench.core.ai.anthropic_provider import AnthropicProvider
        except ImportError as e:
            raise CoreError(
                "AI_NOT_CONFIGURED", "anthropic SDK not installed", hint=_INSTALL_HINT
            ) from e
        return AnthropicProvider(cfg, http_client=http_client)
    try:
        from ontoworkbench.core.ai.openai_provider import OpenAIProvider
    except ImportError as e:
        raise CoreError("AI_NOT_CONFIGURED", "openai SDK not installed", hint=_INSTALL_HINT) from e
    return OpenAIProvider(cfg, http_client=http_client)
