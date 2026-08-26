"""Source editing: GET fileHash baseline + PUT parse-gated overwrite."""

import io

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
