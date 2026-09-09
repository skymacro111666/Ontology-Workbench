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


# --- POST /validation/run (spec 2026-09-08 §2.2) -------------------------

SHAPES_OK = (
    "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
    "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
    "[] a sh:NodeShape ; sh:targetClass <http://www.w3.org/2002/07/owl#Class> ;\n"
    "   sh:property [ sh:path rdfs:comment ; sh:minCount 1 ; sh:severity sh:Warning ] .\n"
)


def _save_shapes(client: TestClient, oid: str, source: str) -> None:
    r = client.put(f"/api/ontologies/{oid}/validation/shapes", json={"source": source})
    assert r.status_code == 200, r.text


def test_run_without_any_source_is_400_shapes_required(client: TestClient) -> None:
    """Neither stored shapes nor inline source: 400 SHAPES_REQUIRED."""
    oid = _setup(client)
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={})
    assert r.status_code == 400 and r.json()["code"] == "SHAPES_REQUIRED"


def test_run_returns_normalized_report(client: TestClient) -> None:
    """Real pyrudof run: warning for the comment-less class, camelCase payload."""
    oid = _setup(client)
    _save_shapes(client, oid, SHAPES_OK)
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["conforms"] is False and d["counts"]["warning"] == 1
    assert d["engine"] == "pyrudof" and d["elapsedMs"] >= 0
    row = d["results"][0]
    assert row["severity"] == "warning" and "http://example.org/A" in row["focusIri"]


def test_run_inline_source_beats_stored(client: TestClient) -> None:
    """Inline source shadows the saved shapes; empty target = conforms."""
    oid = _setup(client)
    _save_shapes(client, oid, SHAPES_OK)
    inline = (
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "[] a sh:NodeShape ; sh:targetClass <http://no.match/x> .\n"
    )
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={"source": inline})
    assert r.status_code == 200
    assert r.json()["data"]["conforms"] is True


def test_run_timeout_maps_504(client: TestClient, monkeypatch) -> None:
    """ValidationTimeout escapes as 504 VALIDATION_TIMEOUT."""
    oid = _setup(client)
    _save_shapes(client, oid, SHAPES_OK)
    import ontoworkbench.server.routers.validation as v

    def _hang(engine, data_path, shapes_source, fmt, timeout_s):
        raise v.ValidationTimeout("0.001")

    monkeypatch.setattr(v, "run_validated", _hang)
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={})
    assert r.status_code == 504 and r.json()["code"] == "VALIDATION_TIMEOUT"


def test_run_engine_failure_maps_500(client: TestClient, monkeypatch) -> None:
    """EngineFailure escapes as 500 VALIDATION_ENGINE with the detail."""
    oid = _setup(client)
    _save_shapes(client, oid, SHAPES_OK)
    import ontoworkbench.server.routers.validation as v

    def _boom(engine, data_path, shapes_source, fmt, timeout_s):
        raise v.EngineFailure("rudof exploded")

    monkeypatch.setattr(v, "run_validated", _boom)
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={})
    assert r.status_code == 500 and r.json()["code"] == "VALIDATION_ENGINE"
