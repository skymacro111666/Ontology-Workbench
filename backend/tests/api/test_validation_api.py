"""Validation shapes storage + presets payload (spec 2026-09-08 §2.1)."""

import io

from fastapi.testclient import TestClient

TTL = b"@prefix ex: <http://example.org/> .\nex:A a <http://www.w3.org/2002/07/owl#Class> .\n"


def _setup(client: TestClient) -> str:
    """Upload a tiny ontology and return its id."""
    r = client.post("/api/ontologies", files={"file": ("m.ttl", io.BytesIO(TTL), "text/turtle")})
    assert r.status_code == 201
    return r.json()["data"]["id"]


def test_get_shapes_defaults_and_presets(client: TestClient) -> None:
    """Fresh ontology: null source/updatedAt, presets in bundle order."""
    oid = _setup(client)
    r = client.get(f"/api/ontologies/{oid}/validation/shapes")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["source"] is None and d["updatedAt"] is None
    ids = [p["id"] for p in d["presets"]]
    assert ids == ["obo-integrity", "minimal-label"]
    assert "sh:qualifiedMinCount 1" in d["presets"][0]["source"]


def test_put_shapes_roundtrip_and_invalid(client: TestClient) -> None:
    """PUT persists and echoes afWarnings; non-Turtle is 400 SHAPES_INVALID."""
    oid = _setup(client)
    src = "@prefix sh: <http://www.w3.org/ns/shacl#> .\n[] a sh:NodeShape .\n"
    r = client.put(f"/api/ontologies/{oid}/validation/shapes", json={"source": src})
    assert r.status_code == 200 and r.json()["data"]["afWarnings"] == []
    d = client.get(f"/api/ontologies/{oid}/validation/shapes").json()["data"]
    assert d["source"] == src and d["updatedAt"] is not None

    bad = client.put(f"/api/ontologies/{oid}/validation/shapes", json={"source": "not turtle {"})
    assert bad.status_code == 400 and bad.json()["code"] == "SHAPES_INVALID"
    assert "hint" in bad.json()


def test_put_shapes_flags_shacl_af(client: TestClient) -> None:
    """SHACL-AF vocabulary still saves (200) but surfaces a warning list."""
    oid = _setup(client)
    af = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "[] sh:sparql [ sh:select '''SELECT ?x WHERE { ?x ?p ?o }''' ] .\n"
    )
    r = client.put(f"/api/ontologies/{oid}/validation/shapes", json={"source": af})
    assert r.status_code == 200
    assert "sh:sparql" in r.json()["data"]["afWarnings"]
