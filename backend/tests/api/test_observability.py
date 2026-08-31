"""/metrics exposed and access log emitted as JSON with request id."""

import json
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.core.store import LocalUserDirStore
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


def test_access_log_route_client_and_started_at(tmp_path: Path, capsys) -> None:
    """http.request carries route, ontology_id, client fields, started_at.

    Observability spec §2: parameterized route template, extracted ontology
    id, client ip / user agent, and the request-entry timestamp.
    """
    db_url = f"sqlite:///{tmp_path}/test.db"
    Base.metadata.create_all(init_engine(db_url))
    app = create_app(Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "log_dir": tmp_path}))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "admin", "password": "admin123!"})
        token = c.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123!"}
        ).json()["data"]["token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "test-agent/1.0",
            "X-Forwarded-For": "203.0.113.5, 10.0.0.1",
        }
        oid = c.post("/api/samples/pizza", headers=headers).json()["data"]["id"]
        c.get(f"/api/ontologies/{oid}/meta", headers=headers)
        c.get("/api/nope")  # unmatched → route falls back to the raw path

    lines = {
        (r["method"], r["path"]): r
        for r in map(json.loads, capsys.readouterr().out.splitlines())
        if r.get("event") == "http.request"
    }
    sample = lines[("POST", "/api/samples/pizza")]
    assert sample["route"] == "/api/samples/{name}"
    assert "ontology_id" not in sample  # no ontology_id path param on this route

    meta = lines[("GET", f"/api/ontologies/{oid}/meta")]
    assert meta["route"] == "/api/ontologies/{ontology_id}/meta"
    assert meta["ontology_id"] == oid
    assert meta["client_ip"] == "203.0.113.5"  # first X-Forwarded-For hop
    assert meta["user_agent"] == "test-agent/1.0"
    started = datetime.fromisoformat(meta["started_at"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(meta["timestamp"].replace("Z", "+00:00"))
    assert started <= finished  # timestamp = completion (spec §1)

    missing = lines[("GET", "/api/nope")]
    assert missing["status"] == 404
    assert missing["route"] == "/api/nope"  # unmatched: raw path fallback
    assert missing["client_ip"] == "testclient"  # no proxy header → client host


TTL = "@prefix : <http://ex.org/o#> .\n:C a <http://www.w3.org/2002/07/owl#Class> .\n"


def test_import_event_staged_and_linked(tmp_path: Path, capsys) -> None:
    """ontology.import carries request_id and the seven staged timings.

    The request_id equals the http.request line of the same upload; failures
    come out as level=error with error_code/error_type (spec §3).
    """
    db_url = f"sqlite:///{tmp_path}/test.db"
    Base.metadata.create_all(init_engine(db_url))
    app = create_app(Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "log_dir": tmp_path}))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "admin", "password": "admin123!"})
        token = c.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123!"}
        ).json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}
        up = c.post(
            "/api/ontologies", headers=headers, files={"file": ("mini.ttl", TTL, "text/turtle")}
        )
        assert up.status_code == 201
        bad = c.post(
            "/api/ontologies",
            headers=headers,
            files={"file": ("broken.ttl", b"@@ not turtle @@", "text/turtle")},
        )
        assert bad.status_code == 400  # PARSE_FAILED envelope maps to 400

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    http_up = next(
        r
        for r in records
        if r.get("event") == "http.request"
        and r.get("path") == "/api/ontologies"
        and r.get("status") == 201
    )
    imp = next(r for r in records if r.get("event") == "ontology.import")
    assert imp["source"] == "http"
    assert imp["request_id"] == http_up["request_id"]  # concurrent-safe linkage
    for stage in ("read_ms", "parse_ms", "ir_ms", "store_ms", "db_ms", "index_ms", "total_ms"):
        assert imp[stage] >= 0
    stages = sum(imp[s] for s in ("read_ms", "parse_ms", "ir_ms", "store_ms", "db_ms", "index_ms"))
    assert stages <= imp["total_ms"] + 50  # misc overhead tolerance

    failed = next(r for r in records if r.get("event") == "ontology.import_failed")
    assert failed["level"] == "error"
    assert failed["error_code"] == "PARSE_FAILED"
    assert failed["error_type"]
    assert failed["request_id"]
    assert failed["source"] == "http"


def test_delete_audit_events(tmp_path: Path, capsys, monkeypatch) -> None:
    """DELETE emits ontology.delete on success, delete_failed on a broken step.

    Success carries the full audit context; a raising stage turns into
    level=error with failed_stage (observability spec §4).
    """
    db_url = f"sqlite:///{tmp_path}/test.db"
    Base.metadata.create_all(init_engine(db_url))
    app = create_app(Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "log_dir": tmp_path}))
    with TestClient(app) as c:
        c.post("/api/auth/setup", json={"username": "admin", "password": "admin123!"})
        token = c.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123!"}
        ).json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}
        oid = c.post(
            "/api/ontologies", headers=headers, files={"file": ("mini.ttl", TTL, "text/turtle")}
        ).json()["data"]["id"]
        assert c.delete(f"/api/ontologies/{oid}", headers=headers).status_code == 200

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    http_del = next(
        r
        for r in records
        if r.get("event") == "http.request" and r.get("method") == "DELETE" and r["status"] == 200
    )
    dele = next(r for r in records if r.get("event") == "ontology.delete")
    assert dele["request_id"] == http_del["request_id"]
    assert dele["ontology_id"] == oid
    assert dele["filename"] == "mini.ttl"
    assert dele["size_bytes"] == len(TTL)
    assert dele["layout_deleted"] is False  # no layout was ever saved
    assert dele["cache_evicted"] in (True, False)
    assert dele["duration_ms"] >= 0
    assert dele["level"] == "info"

    # A store failure mid-delete leaves the audit trail with the broken stage
    # (raise_server_exceptions=False surfaces the 500 as a response).
    with TestClient(app, raise_server_exceptions=False) as c:
        token = c.post(
            "/api/auth/login", json={"username": "admin", "password": "admin123!"}
        ).json()["data"]["token"]
        headers = {"Authorization": f"Bearer {token}"}
        oid2 = c.post(
            "/api/ontologies", headers=headers, files={"file": ("mini.ttl", TTL, "text/turtle")}
        ).json()["data"]["id"]

        def boom(self, user_id, ontology_id):
            raise RuntimeError("disk on fire")

        monkeypatch.setattr(LocalUserDirStore, "delete", boom)
        assert c.delete(f"/api/ontologies/{oid2}", headers=headers).status_code == 500

    failed = next(
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if '"event": "ontology.delete_failed"' in line
    )
    assert failed["level"] == "error"
    assert failed["failed_stage"] == "store"
    assert failed["error_type"] == "RuntimeError"
    assert failed["ontology_id"] == oid2
    assert failed["request_id"]
