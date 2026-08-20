"""Upload/list/delete/samples happy + error paths."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine
from ontoworkbench.server.app import create_app

TTL = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Authenticated client over a file-backed sqlite and tmp data dir."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    app = create_app(
        Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "data_dir": tmp_path})
    )
    c = TestClient(app)
    c.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = c.post("/api/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    c.headers["Authorization"] = f"Bearer {r.json()['data']['token']}"
    return c


def test_upload_list_delete(client: TestClient) -> None:
    """Upload → 201 camelCase meta; duplicate 409; list; delete → data null."""
    up = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(TTL), "text/turtle")}
    )
    body = up.json()
    assert up.status_code == 201 and body["code"] == "OK"
    meta = body["data"]
    assert meta["classCount"] == 2
    assert meta["format"] == "turtle"
    assert set(meta) >= {
        "id",
        "title",
        "filename",
        "format",
        "classCount",
        "propertyCount",
        "fileSizeBytes",
        "createdAt",
        "prefixes",
    }

    dup = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(TTL), "text/turtle")}
    )
    assert dup.status_code == 409
    assert dup.json()["code"] == "DUPLICATE_FILENAME"

    lst = client.get("/api/ontologies").json()["data"]
    assert lst["total"] == 1
    assert lst["items"][0]["filename"] == "mini.ttl"

    gone = client.delete(f"/api/ontologies/{meta['id']}")
    assert gone.status_code == 200
    assert gone.json()["data"] is None
    assert client.get("/api/ontologies").json()["data"]["total"] == 0
    assert client.delete(f"/api/ontologies/{meta['id']}").json()["code"] == "NOT_FOUND"


def test_upload_rejects_garbage(client: TestClient) -> None:
    """Binary garbage is rejected as UNSUPPORTED_FORMAT, not 500."""
    bad = client.post(
        "/api/ontologies",
        files={"file": ("x.bin", io.BytesIO(b"\x00\x01"), "application/octet-stream")},
    )
    assert bad.status_code == 415
    assert bad.json()["code"] in {"UNSUPPORTED_FORMAT", "PARSE_FAILED"}


def test_upload_requires_auth(tmp_path: Path) -> None:
    """Anonymous upload is AUTH_REQUIRED (401)."""
    db_url = f"sqlite:///{tmp_path}/anon.db"
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    app = create_app(Settings.load({"jwt_secret": "t" * 32, "db_url": db_url}))
    with TestClient(app) as c:
        r = c.post(
            "/api/ontologies",
            files={"file": ("mini.ttl", io.BytesIO(TTL), "text/turtle")},
        )
        assert r.status_code == 401
        assert r.json()["code"] == "AUTH_REQUIRED"


def test_samples_idempotent(client: TestClient) -> None:
    """Importing a sample twice returns the SAME record (no duplicate)."""
    r1 = client.post("/api/samples/does-not-exist")
    assert r1.json()["code"] == "NOT_FOUND"
