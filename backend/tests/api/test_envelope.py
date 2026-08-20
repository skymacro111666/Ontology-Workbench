"""Envelope shape must be identical for success and error (spec §6)."""

from pathlib import Path

from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.server.app import create_app


def client(tmp_dir: Path | None = None) -> TestClient:
    """Build a sync client against a freshly assembled app."""
    overrides: dict = {"db_url": "sqlite:///:memory:"}
    if tmp_dir is not None:
        overrides["log_dir"] = tmp_dir
    return TestClient(create_app(Settings.load(overrides)))


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


def test_method_not_allowed_maps_not_found() -> None:
    """405 routes are NOT_FOUND at 404 (ruling: no METHOD_NOT_ALLOWED code)."""
    with client() as c:
        r = c.put("/api/health")
        assert r.status_code == 404
        assert r.json()["code"] == "NOT_FOUND"


def test_cors_preflight_for_local_dev() -> None:
    """Vite dev origin may preflight; CORS headers come back."""
    with client() as c:
        r = c.options(
            "/api/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_unhandled_error_keeps_request_id_header(tmp_path: Path) -> None:
    """500s still carry X-Request-ID matching the body (handler sets it)."""
    app = create_app(Settings.load({"db_url": "sqlite:///:memory:", "log_dir": tmp_path}))

    @app.get("/api/boom")
    def boom() -> dict:
        raise RuntimeError("boom")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/api/boom")
        assert r.status_code == 500
        assert r.json()["code"] == "INTERNAL_ERROR"
        assert r.headers["x-request-id"] == r.json()["request_id"]
        assert r.json()["request_id"] != "-"


def test_validation_hint_omits_input_values(tmp_path: Path) -> None:
    """422 hint carries loc/msg/type only — never the rejected input itself."""
    with client(tmp_path) as c:
        r = c.post("/api/auth/setup", json={"username": "ab", "password": "x"})
        assert r.json()["code"] == "VALIDATION_ERROR"
        hint = r.json()["hint"]
        assert "loc" in hint and "msg" in hint
        assert "input" not in hint


def test_client_supplied_request_id_is_sanitized(tmp_path: Path) -> None:
    """A malformed client X-Request-ID is replaced, not echoed."""
    with client(tmp_path) as c:
        r = c.get("/api/health", headers={"X-Request-ID": "bad id<script>"})
        rid = r.headers["x-request-id"]
        assert rid == r.json()["request_id"]
        assert "<script>" not in rid and " " not in rid
