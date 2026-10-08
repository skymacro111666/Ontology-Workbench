"""core/ai neutral types: env config precedence and defaults."""

import pytest

from ontoworkbench.core.ai.base import AiConfig


def test_from_env_reads_unprefixed_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """AI_* env vars (no OW_ prefix) land in the config verbatim."""
    monkeypatch.setenv("AI_MODEL_PROVIDER", "anthropic")
    monkeypatch.setenv("AI_BASE_URL", "https://api.example.com")
    monkeypatch.setenv("AI_API_KEY", "sk-x")
    monkeypatch.setenv("AI_MODEL", "claude-fable-5-1")
    cfg = AiConfig.from_env()
    assert cfg.provider == "anthropic"
    assert cfg.base_url == "https://api.example.com"
    assert cfg.api_key == "sk-x"
    assert cfg.model == "claude-fable-5-1"
    assert cfg.configured


def test_from_env_defaults_and_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty env: openai-compatible default family, blank model/key → unconfigured."""
    for var in ("AI_MODEL_PROVIDER", "AI_BASE_URL", "AI_API_KEY", "AI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    cfg = AiConfig.from_env()
    assert cfg.provider == "openai"
    assert cfg.base_url is None and cfg.api_key == "" and cfg.model == ""
    assert not cfg.configured
