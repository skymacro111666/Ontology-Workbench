"""Source editing: GET fileHash baseline + PUT parse-gated overwrite."""

import io
import uuid

from fastapi.testclient import TestClient

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal .
"""


def _upload(client: TestClient, data: bytes = MINI, name: str = "mini.ttl") -> tuple[str, dict]:
    """Upload bytes and return (oid, upload meta)."""
    r = client.post("/api/ontologies", files={"file": (name, io.BytesIO(data), "text/turtle")})
    return r.json()["data"]["id"], r.json()["data"]


def test_source_returns_file_hash(client: TestClient) -> None:
    """GET /source carries the row's fileHash — the edit baseline."""
    oid, meta = _upload(client)
    src = client.get(f"/api/ontologies/{oid}/source").json()["data"]
    assert src["fileHash"] == meta["fileHash"]
    assert src["content"].encode() == MINI


MINI2 = MINI + b"ex:Cat a owl:Class ; rdfs:subClassOf ex:Animal .\n"


def _put(client: TestClient, oid: str, content: bytes, base: str):
    return client.put(
        f"/api/ontologies/{oid}/source",
        json={"content": content.decode(), "baseFileHash": base},
    )


def test_put_source_happy_path(client: TestClient) -> None:
    """PUT rewrites file+row, warms cache, serves new hash and counts."""
    oid, meta = _upload(client)
    r = _put(client, oid, MINI2, meta["fileHash"])
    body = r.json()
    assert r.status_code == 200 and body["code"] == "OK"
    new_hash = body["data"]["fileHash"]
    assert new_hash != meta["fileHash"]
    assert body["data"]["classCount"] == 4  # +ex:Cat

    src = client.get(f"/api/ontologies/{oid}/source").json()["data"]
    assert src["content"].encode() == MINI2 and src["fileHash"] == new_hash
    # Row counts refreshed.
    assert client.get(f"/api/ontologies/{oid}/meta").json()["data"]["classCount"] == 4
    # Cache is fresh: the new class shows up in the tree immediately.
    kids = client.get(
        f"/api/ontologies/{oid}/tree", params={"parent": "http://example.org/Animal"}
    ).json()["data"]
    assert "ex:Cat" in [k["curie"] for k in kids]


def test_put_source_parse_failure_keeps_file(client: TestClient) -> None:
    """A syntax error 400s and leaves file + hash untouched."""
    oid, meta = _upload(client)
    r = _put(client, oid, b"this is { not turtle", meta["fileHash"])
    assert r.status_code == 400 and r.json()["code"] == "PARSE_FAILED"
    src = client.get(f"/api/ontologies/{oid}/source").json()["data"]
    assert src["content"].encode() == MINI and src["fileHash"] == meta["fileHash"]


def test_put_source_stale_hash_conflicts(client: TestClient) -> None:
    """A stale baseFileHash 409s and leaves the file untouched."""
    oid, meta = _upload(client)
    r = _put(client, oid, MINI2, "0" * 64)
    assert r.status_code == 409 and r.json()["code"] == "EDIT_CONFLICT"
    assert client.get(f"/api/ontologies/{oid}/source").json()["data"]["content"].encode() == MINI


def test_put_source_not_found(client: TestClient) -> None:
    """Unknown and malformed ids are uniform 404s."""
    r = client.put(
        f"/api/ontologies/{uuid.uuid4()}/source",
        json={"content": "", "baseFileHash": "x"},
    )
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"
    r2 = _put(client, "not-a-uuid", MINI2, "x")
    assert r2.status_code == 404


def test_put_source_validation_and_size(client: TestClient, monkeypatch) -> None:
    """Missing baseFileHash 422s; oversized content 413s (cap patched small)."""
    oid, meta = _upload(client)
    r = client.put(f"/api/ontologies/{oid}/source", json={"content": MINI2.decode()})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"

    from ontoworkbench.server.routers import ontologies as ontologies_router

    monkeypatch.setattr(ontologies_router, "MAX_UPLOAD", 10)
    r2 = _put(client, oid, MINI2, meta["fileHash"])
    assert r2.status_code == 413 and r2.json()["code"] == "UPLOAD_TOO_LARGE"


def test_put_source_recomputes_title(client: TestClient) -> None:
    """A dc:title appearing in the edit renames the ontology row."""
    oid, meta = _upload(client)
    assert meta["title"] == "mini"  # filename stem fallback
    titled = MINI + (
        b"@prefix dc: <http://purl.org/dc/terms/> .\n"
        b'ex:mini a owl:Ontology ; dc:title "Titled"@en .\n'
    )
    r = _put(client, oid, titled, meta["fileHash"])
    assert r.json()["data"]["title"] == "Titled"
