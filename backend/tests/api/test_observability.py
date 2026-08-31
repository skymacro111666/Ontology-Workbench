"""/metrics exposed and access log emitted as JSON with request id."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine
from ontoworkbench.server.app import create_app


def test_metrics_and_access_log(tmp_path: Path, capsys) -> None:
    """/metrics serves business metric families; access log is JSON on stdout."""
    settings = Settings.load(
        {
            "log_dir": tmp_path,
            "jwt_secret": "t" * 32,
            "db_url": "sqlite:///:memory:",
        }
    )
    app = create_app(settings)
    with TestClient(app) as c:  # context manager runs startup (metrics)
        m = c.get("/metrics")
        assert m.status_code == 200
        assert "ow_parse_seconds" in m.text
        assert "ow_uploads_total" in m.text
        c.get("/api/health")

    line = capsys.readouterr().out.strip().splitlines()[-1]
    record = json.loads(line)
    assert record["event"] == "http.request"
    assert record["status"] == 200
    assert record["path"] == "/api/health"
    assert "duration_ms" in record
    assert record["request_id"] != "-"
    assert "user_id" in record
    files = list(tmp_path.glob("ow-*.log"))
    assert len(files) == 1  # daily file created


def test_access_log_user_id_never_null(tmp_path: Path, capsys) -> None:
    """user_id carries a value on every access-log line.

    The acting user where the request authenticated (dependency, login, or
    setup), else "anonymous" — never None. Contextvar sets inside the route
    never cross BaseHTTPMiddleware's call_next boundary, so the log reads
    request.state instead.
    """
    db_url = f"sqlite:///{tmp_path}/test.db"
    Base.metadata.create_all(init_engine(db_url))
    app = create_app(Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "log_dir": tmp_path}))
    with TestClient(app) as c:
        uid = c.post("/api/auth/setup", json={"username": "admin", "password": "admin123!"}).json()[
            "data"
        ]["id"]
        c.get("/api/health")  # anonymous even with a user existing
        creds = {"username": "admin", "password": "admin123!"}
        token = c.post("/api/auth/login", json=creds).json()["data"]["token"]
        c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})

    users = {
        (r["method"], r["path"]): r["user_id"]
        for r in map(json.loads, capsys.readouterr().out.splitlines())
        if r.get("event") == "http.request"
    }
    assert users[("GET", "/api/health")] == "anonymous"
    assert users[("POST", "/api/auth/setup")] == uid
    assert users[("POST", "/api/auth/login")] == uid
    assert users[("GET", "/api/auth/me")] == uid
