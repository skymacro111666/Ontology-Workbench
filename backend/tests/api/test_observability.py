"""/metrics exposed and access log emitted as JSON with request id."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
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
