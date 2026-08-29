"""Import outcomes must leave an ops trace beyond the HTTP envelope.

The HTTP layer already logs errors generically (test_error_logging); these
tests pin the import-specific events an operator greps for: what file, how
big, how long, and — on failure — why it was rejected.
"""

import io
import logging

from fastapi.testclient import TestClient

GOOD_TTL = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:A a owl:Class .
"""
BAD_TTL = b"@prefix 5gc: <http://x#> .\n5gc:A a <http://www.w3.org/2002/07/owl#Class> .\n"


def test_upload_success_logs_import_event(client: TestClient, caplog: logging.Logger) -> None:
    """A successful upload logs ontology.import with file, timing and counts."""
    with caplog.at_level(logging.INFO, logger="ow.imports"):
        r = client.post(
            "/api/ontologies",
            files={"file": ("ok.ttl", io.BytesIO(GOOD_TTL), "text/turtle")},
        )
    assert r.status_code == 201
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert '"ontology.import"' in logged
    assert '"filename": "ok.ttl"' in logged
    assert '"format": "turtle"' in logged
    assert '"class_count": 1' in logged
    assert '"size_bytes": ' in logged
    assert '"parse_ms": ' in logged
    assert '"total_ms": ' in logged


def test_duplicate_upload_logs_import_failed(client: TestClient, caplog: logging.Logger) -> None:
    """A rejected import (duplicate filename) logs ontology.import_failed with the code."""
    files = {"file": ("dup.ttl", io.BytesIO(GOOD_TTL), "text/turtle")}
    client.post("/api/ontologies", files=files)
    with caplog.at_level(logging.WARNING, logger="ow.imports"):
        r = client.post("/api/ontologies", files=files)
    assert r.status_code == 409
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert '"ontology.import_failed"' in logged
    assert '"filename": "dup.ttl"' in logged
    assert "DUPLICATE_FILENAME" in logged


def test_parse_failure_logs_import_failed(client: TestClient, caplog: logging.Logger) -> None:
    """A parse-rejected upload logs ontology.import_failed with PARSE_FAILED."""
    with caplog.at_level(logging.WARNING, logger="ow.imports"):
        r = client.post(
            "/api/ontologies",
            files={"file": ("bad.ttl", io.BytesIO(BAD_TTL), "text/turtle")},
        )
    assert r.status_code == 400
    logged = " ".join(rec.getMessage() for rec in caplog.records)
    assert '"ontology.import_failed"' in logged
    assert '"filename": "bad.ttl"' in logged
    assert "PARSE_FAILED" in logged
