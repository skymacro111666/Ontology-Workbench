"""Validation shapes storage + presets payload (spec 2026-09-08 §2.1)."""

import io

from fastapi.testclient import TestClient

TTL = b"@prefix ex: <http://example.org/> .\nex:A a <http://www.w3.org/2002/07/owl#Class> .\n"

# M2 忽略已废弃: ex:Old carries owl:deprecated true, ex:A does not.
DEP_TTL = (
    b"@prefix ex: <http://example.org/> .\n"
    b"@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    b"ex:A a owl:Class .\n"
    b"ex:Old a owl:Class ; owl:deprecated true .\n"
)


def _setup(client: TestClient, ttl: bytes = TTL) -> str:
    """Upload a tiny ontology and return its id."""
    r = client.post("/api/ontologies", files={"file": ("m.ttl", io.BytesIO(ttl), "text/turtle")})
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


def test_run_drops_deprecated_focus_by_default(client: TestClient) -> None:
    """M2 忽略已废弃 default-on: deprecated-focus results vanish, count rides along."""
    oid = _setup(client, DEP_TTL)
    _save_shapes(client, oid, SHAPES_OK)
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["deprecatedFiltered"] == 1
    assert [x["focusIri"] for x in d["results"]] == ["http://example.org/A"]


def test_run_include_deprecated_keeps_all(client: TestClient) -> None:
    """includeDeprecated=true opts back into the raw engine report."""
    oid = _setup(client, DEP_TTL)
    _save_shapes(client, oid, SHAPES_OK)
    r = client.post(f"/api/ontologies/{oid}/validation/run", json={"includeDeprecated": True})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["deprecatedFiltered"] == 0
    assert len(d["results"]) == 2


def test_run_reports_total_results(client: TestClient) -> None:
    """Run carries totalResults == the full (post-filter) result count."""
    oid = _setup(client, DEP_TTL)
    _save_shapes(client, oid, SHAPES_OK)
    d = client.post(f"/api/ontologies/{oid}/validation/run", json={}).json()["data"]
    assert d["totalResults"] == 1 and len(d["results"]) == 1


# --- POST /validation/export (B·缓存上次报告) ----------------------------


def _counting_engine(monkeypatch):
    """Spy on the engine runner so tests can assert cache hits vs re-runs."""
    import ontoworkbench.server.routers.validation as v

    calls = {"n": 0}
    real = v.run_validated

    def _spy(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(v, "run_validated", _spy)
    return calls


def test_export_reuses_cached_report(client: TestClient, monkeypatch) -> None:
    """Export after run hits the cache: engine ran once.

    Filter and format toggles ride the same cached turtle without re-running.
    """
    calls = _counting_engine(monkeypatch)
    oid = _setup(client, DEP_TTL)
    _save_shapes(client, oid, SHAPES_OK)
    assert client.post(f"/api/ontologies/{oid}/validation/run", json={}).status_code == 200
    assert calls["n"] == 1

    r1 = client.post(f"/api/ontologies/{oid}/validation/export", json={})
    assert r1.status_code == 200 and calls["n"] == 1  # cache hit
    assert r1.headers["content-type"].startswith("text/csv")
    assert 'filename="m-validation.csv"' in r1.headers["content-disposition"]
    assert r1.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    lines = r1.content.decode("utf-8").splitlines()
    assert lines[0].endswith("severity,focus_iri,focus_curie,path,constraint,message,value")
    assert len(lines) == 2  # header + ex:A (deprecated ex:Old filtered)

    r2 = client.post(f"/api/ontologies/{oid}/validation/export", json={"includeDeprecated": True})
    assert calls["n"] == 1 and len(r2.content.decode("utf-8").splitlines()) == 3

    r3 = client.post(f"/api/ontologies/{oid}/validation/export", json={"format": "json"})
    assert calls["n"] == 1
    assert r3.headers["content-type"].startswith("application/json")
    assert 'filename="m-validation.json"' in r3.headers["content-disposition"]
    d = r3.json()  # 文件下载绕过 envelope,裸载荷
    # 与 run 同口径:废弃警告被滤、剩 A 的 warning、无严重 → conforms 重判 True
    assert d["conforms"] is True and d["totalResults"] == 1 and d["deprecatedFiltered"] == 1
    assert d["counts"]["warning"] == 1 and d["engine"] == "pyrudof"


def test_export_reruns_after_revision_bump(client: TestClient, monkeypatch) -> None:
    """An edit bumps revision → the cached report is stale → export re-runs."""
    calls = _counting_engine(monkeypatch)
    oid = _setup(client)
    _save_shapes(client, oid, SHAPES_OK)
    assert client.post(f"/api/ontologies/{oid}/validation/run", json={}).status_code == 200
    src = client.get(f"/api/ontologies/{oid}/source").json()["data"]
    new_src = src["content"] + "ex:B a <http://www.w3.org/2002/07/owl#Class> .\n"
    assert (
        client.put(
            f"/api/ontologies/{oid}/source",
            json={"content": new_src, "baseFileHash": src["fileHash"]},
        ).status_code
        == 200
    )
    r = client.post(f"/api/ontologies/{oid}/validation/export", json={})
    assert r.status_code == 200 and calls["n"] == 2  # run + stale re-run


def test_export_without_shapes_is_400(client: TestClient) -> None:
    """Neither stored shapes nor inline source: 400 SHAPES_REQUIRED."""
    oid = _setup(client)
    r = client.post(f"/api/ontologies/{oid}/validation/export", json={})
    assert r.status_code == 400 and r.json()["code"] == "SHAPES_REQUIRED"


def test_export_rejects_unknown_format(client: TestClient) -> None:
    """Format is Literal[csv, json]: anything else is a 422."""
    oid = _setup(client)
    _save_shapes(client, oid, SHAPES_OK)
    r = client.post(f"/api/ontologies/{oid}/validation/export", json={"format": "xml"})
    assert r.status_code == 422


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
