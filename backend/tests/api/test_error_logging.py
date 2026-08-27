"""Error responses must leave a trace: handlers log code+reason, not just 4xx."""

import logging

from fastapi.testclient import TestClient

BAD_TTL = b"@prefix 5gc: <http://x#> .\n5gc:A a <http://www.w3.org/2002/07/owl#Class> .\n"
GOOD_TTL = b"@prefix ex: <http://x#> .\nex:A a <http://www.w3.org/2002/07/owl#Class> .\n"


def test_parse_failure_logs_reason(client: TestClient, caplog: logging.Logger) -> None:
    """A rejected upload logs the parse error, not only the 400 envelope."""
    with caplog.at_level(logging.WARNING, logger="ow.errors"):
        r = client.post(
            "/api/ontologies",
            files={"file": ("bad.ttl", BAD_TTL, "text/turtle")},
        )
    assert r.status_code == 400
    assert r.json()["code"] == "PARSE_FAILED"
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert '"http.error"' in logged
    assert "PARSE_FAILED" in logged
    assert "Syntax error" in logged
    assert '"request_id": "' in logged


def test_api_error_logs_code(client: TestClient, caplog: logging.Logger) -> None:
    """ApiError failures (duplicate filename) log with their machine code."""
    files = {"file": ("dup.ttl", GOOD_TTL, "text/turtle")}
    client.post("/api/ontologies", files=files)
    with caplog.at_level(logging.WARNING, logger="ow.errors"):
        r = client.post("/api/ontologies", files=files)
    assert r.status_code == 409
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert "DUPLICATE_FILENAME" in logged
