"""AI settings endpoints: write-only key, DB>env merge, probe."""

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.types import ModelRequest, ModelResponse
from ontoworkbench.server.routers.ai_settings import get_ai_provider

AI_ENV = ("AI_MODEL_PROVIDER", "AI_BASE_URL", "AI_API_KEY", "AI_MODEL")


def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in AI_ENV:
        monkeypatch.delenv(var, raising=False)


def test_put_then_get_never_returns_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT stores the key; GET reports hasKey + last 4 and never the key itself."""
    _clear_env(monkeypatch)
    r = client.put(
        "/api/v1/ai/settings",
        json={
            "provider": "openai",
            "baseUrl": "https://api.test/v1",
            "apiKey": "sk-secret-1234",
            "model": "test-model",
        },
    )
    assert r.status_code == 200
    body = client.get("/api/v1/ai/settings").json()["data"]
    assert body["hasKey"] is True and body["keyLast4"] == "1234"
    assert body["provider"] == "openai" and body["baseUrl"] == "https://api.test/v1"
    assert "sk-secret-1234" not in client.get("/api/v1/ai/settings").text


def test_put_omitted_api_key_keeps_old(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A PUT without apiKey keeps the stored key."""
    _clear_env(monkeypatch)
    client.put("/api/v1/ai/settings", json={"apiKey": "sk-first-9999", "model": "m1"})
    client.put("/api/v1/ai/settings", json={"model": "m2"})
    body = client.get("/api/v1/ai/settings").json()["data"]
    assert body["model"] == "m2" and body["keyLast4"] == "9999"


def test_status_env_fallback_then_db_override(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Status reads env when no row exists; a stored model overrides (source=db)."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("AI_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("AI_API_KEY", "sk-env")
    monkeypatch.setenv("AI_MODEL", "env-model")
    body = client.get("/api/v1/ai/status").json()["data"]
    assert body == {"configured": True, "provider": "openai", "model": "env-model", "source": "env"}

    client.put("/api/v1/ai/settings", json={"model": "db-model"})
    body = client.get("/api/v1/ai/status").json()["data"]
    assert body["model"] == "db-model" and body["source"] == "db" and body["configured"] is True


def test_status_unconfigured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """No row + no env → configured false."""
    _clear_env(monkeypatch)
    assert client.get("/api/v1/ai/status").json()["data"] == {
        "configured": False,
        "provider": "openai",
        "model": "",
        "source": "env",
    }


def test_probe_reports_latency(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /ai/test completes a 1-token probe through the resolved provider."""
    _clear_env(monkeypatch)
    client.put("/api/v1/ai/settings", json={"apiKey": "sk-x", "model": "m"})
    client.app.dependency_overrides[get_ai_provider] = lambda: FakeProvider(
        [ModelResponse(text="pong")]
    )
    try:
        r = client.post("/api/v1/ai/test")
    finally:
        client.app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ok"] is True and data["latencyMs"] >= 0


def test_probe_provider_failure_is_ok_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An upstream probe failure answers {ok: false, message} on the OK envelope."""

    class Exploding(ModelProvider):
        """A provider whose every call fails."""

        async def complete(self, req: ModelRequest) -> ModelResponse:
            raise RuntimeError("upstream down")

        async def stream(self, req: ModelRequest):
            raise RuntimeError("upstream down")  # pragma: no cover - probe uses complete
            yield  # type: ignore[unreachable]

    _clear_env(monkeypatch)
    client.put("/api/v1/ai/settings", json={"apiKey": "sk-x", "model": "m"})
    client.app.dependency_overrides[get_ai_provider] = lambda: Exploding()
    try:
        r = client.post("/api/v1/ai/test")
    finally:
        client.app.dependency_overrides.clear()
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ok"] is False and "upstream" in data["message"]


def test_unconfigured_dependency_raises_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Routes depending on get_ai_provider get a 503 AI_NOT_CONFIGURED envelope.

    Exercised through the probe endpoint (the SPA mount swallows routes added
    after create_app, so an ad-hoc check route would 404).
    """
    _clear_env(monkeypatch)
    r = client.post("/api/v1/ai/test")
    assert r.status_code == 503
    assert r.json()["code"] == "AI_NOT_CONFIGURED"
    assert "AI_MODEL_PROVIDER" in (r.json()["hint"] or "")
