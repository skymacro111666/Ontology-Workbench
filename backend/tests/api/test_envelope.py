"""Envelope shape must be identical for success and error (spec §6)."""

from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.server.app import create_app


def client() -> TestClient:
    """Build a sync client against a freshly assembled app."""
    app = create_app(Settings.load({"db_url": "sqlite:///:memory:"}))
    return TestClient(app)


def test_success_and_error_share_five_fields() -> None:
    """Success and error responses carry the same five-field envelope."""
    with client() as c:
        ok = c.get("/api/health")  # demo route registered in app factory
        assert set(ok.json()) == {"code", "message", "data", "hint", "request_id"}
        assert ok.json()["code"] == "OK"
        missing = c.get("/api/does-not-exist")
        assert set(missing.json()) == {"code", "message", "data", "hint", "request_id"}
        assert missing.json()["code"] == "NOT_FOUND"
        assert missing.json()["data"] is None
        assert missing.headers["x-request-id"] == missing.json()["request_id"]
