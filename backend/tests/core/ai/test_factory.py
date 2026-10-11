"""Factory: protocol dispatch + missing-SDK error."""

import builtins
import sys

import pytest

from ontoworkbench.core.ai import get_provider
from ontoworkbench.core.ai.base import AiConfig
from ontoworkbench.core.errors import CoreError


def test_anthropic_dispatch() -> None:
    """provider='anthropic' builds the Anthropic adapter."""
    cfg = AiConfig(provider="anthropic", base_url=None, api_key="k", model="m")
    assert type(get_provider(cfg)).__name__ == "AnthropicProvider"


def test_openai_is_default_family() -> None:
    """Any other provider string (incl. typos) falls back to OpenAI-compatible."""
    cfg = AiConfig(provider="openai", base_url=None, api_key="k", model="m")
    assert type(get_provider(cfg)).__name__ == "OpenAIProvider"
    cfg2 = AiConfig(provider="whatever", base_url=None, api_key="k", model="m")
    assert type(get_provider(cfg2)).__name__ == "OpenAIProvider"


def test_missing_sdk_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blocked SDK import surfaces as AI_NOT_CONFIGURED with an install hint."""
    # Earlier tests in the file already imported the adapter (and the SDK with
    # it) — evict both so the blocked import is actually exercised.
    sys.modules.pop("openai", None)
    sys.modules.pop("ontoworkbench.core.ai.openai_provider", None)
    real_import = builtins.__import__

    def no_openai(name: str, *args: object, **kwargs: object) -> object:
        if name == "openai":
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_openai)
    cfg = AiConfig(provider="openai", base_url=None, api_key="k", model="m")
    with pytest.raises(CoreError) as ei:
        get_provider(cfg)
    assert ei.value.code == "AI_NOT_CONFIGURED"
    assert "reinstall" in (ei.value.hint or "")
