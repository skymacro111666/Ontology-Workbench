"""Ontology-level lifecycle events; delete events survive their ontology."""

from typing import Any

from fastapi.testclient import TestClient

from ontoworkbench.db.models import MutationEvent
from ontoworkbench.db.session import sessionmaker_or_fail
from tests.api.test_source_edit import MINI2, _put, _upload


def _events(client: TestClient, oid: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/ontologies/{oid}/events").json()["data"]["items"]


def test_upload_import_event(client: TestClient) -> None:
    """Upload lands one ontology.import row with filename/format/counts."""
    oid, meta = _upload(client)
    items = _events(client, oid)
    assert [e["action"] for e in items] == ["ontology.import"]
    detail = items[0]["detail"]
    assert detail["filename"] == "mini.ttl"
    assert detail["provenance"] == "upload"
    assert detail["counts"]["classes"] == 3  # MINI: Thing/Animal/Dog


def test_sample_import_event(client: TestClient) -> None:
    """Sample import carries provenance=sample."""
    r = client.post("/api/v1/samples/pizza")
    assert r.status_code == 201
    oid = r.json()["data"]["id"]
    detail = _events(client, oid)[0]["detail"]
    assert detail["provenance"] == "sample"


def test_source_replace_event(client: TestClient) -> None:
    """PUT /source records the fileHash change and new counts."""
    oid, meta = _upload(client)
    r = _put(client, oid, MINI2, meta["fileHash"])
    assert r.status_code == 200
    new_hash = r.json()["data"]["fileHash"]
    items = _events(client, oid)
    assert [e["action"] for e in items] == ["source.replace", "ontology.import"]
    detail = items[0]["detail"]
    assert detail["filename"] == "mini.ttl"
    assert detail["changes"]["fileHash"]["from"] == meta["fileHash"]
    assert detail["changes"]["fileHash"]["to"] == new_hash
    assert detail["counts"]["classes"] == 4  # + Cat


def test_delete_ontology_leaves_event(client: TestClient) -> None:
    """The oid-scoped feed dies with the ontology; the journal row survives."""
    oid, meta = _upload(client)
    assert client.delete(f"/api/v1/ontologies/{oid}").status_code == 200
    assert client.get(f"/api/v1/ontologies/{oid}/events").status_code == 404

    with sessionmaker_or_fail()() as s:
        rows = list(s.query(MutationEvent).filter(MutationEvent.action == "ontology.delete"))
    hit = next(r for r in rows if r.detail.get("ontologyId") == oid)
    assert hit.ontology_id is None  # user scope — spec §8.1
    assert hit.detail["filename"] == "mini.ttl"
    assert hit.detail["counts"]["classes"] == 3
