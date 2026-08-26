"""Canvas layout persistence: GET/PUT/DELETE /api/ontologies/{id}/layout.

Positions are pure UI state (no RDF semantics): no optimistic lock, plain
last-write-wins, one JSON row per ontology (design spec 2026-08-26 §3).
"""

import io

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:A a owl:Class .
"""


def _upload(client) -> str:
    files = {"file": ("mini.ttl", io.BytesIO(MINI), "text/turtle")}
    r = client.post("/api/ontologies", files=files)
    assert r.status_code == 201
    return r.json()["data"]["id"]


def test_layout_roundtrip_overwrite_and_reset(client) -> None:
    """PUT then GET roundtrips; PUT overwrites; DELETE resets."""
    oid = _upload(client)
    # Never saved: empty map, not 404.
    r = client.get(f"/api/ontologies/{oid}/layout")
    assert r.status_code == 200
    assert r.json()["data"] == {"positions": {}}

    pos = {"http://example.org/A": {"x": 12.5, "y": -3.0}}
    r = client.put(f"/api/ontologies/{oid}/layout", json={"positions": pos})
    assert r.status_code == 200
    assert r.json()["data"]["positions"] == pos
    r = client.get(f"/api/ontologies/{oid}/layout")
    assert r.json()["data"]["positions"] == pos

    # PUT replaces the whole map (overwrite, not merge).
    r = client.put(f"/api/ontologies/{oid}/layout", json={"positions": {}})
    assert r.json()["data"]["positions"] == {}

    # DELETE resets to the never-saved state.
    client.put(f"/api/ontologies/{oid}/layout", json={"positions": pos})
    r = client.delete(f"/api/ontologies/{oid}/layout")
    assert r.status_code == 200
    r = client.get(f"/api/ontologies/{oid}/layout")
    assert r.json()["data"] == {"positions": {}}


def test_layout_unknown_or_malformed_ontology_404(client) -> None:
    """Unknown or malformed ids are a uniform 404."""
    r = client.get("/api/ontologies/00000000-0000-0000-0000-000000000000/layout")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"
    r = client.put("/api/ontologies/not-a-uuid/layout", json={"positions": {}})
    assert r.status_code == 404


def test_layout_rejects_oversized_payload(client) -> None:
    """More than 5000 entries is rejected as VALIDATION_ERROR."""
    oid = _upload(client)
    big = {f"http://example.org/n{i}": {"x": 1.0, "y": 2.0} for i in range(5001)}
    r = client.put(f"/api/ontologies/{oid}/layout", json={"positions": big})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_layout_gone_after_ontology_deleted(client) -> None:
    """Deleting the ontology takes its layout row with it."""
    oid = _upload(client)
    client.put(
        f"/api/ontologies/{oid}/layout",
        json={"positions": {"http://example.org/A": {"x": 1.0, "y": 1.0}}},
    )
    r = client.delete(f"/api/ontologies/{oid}")
    assert r.status_code == 200
    r = client.get(f"/api/ontologies/{oid}/layout")
    assert r.status_code == 404
