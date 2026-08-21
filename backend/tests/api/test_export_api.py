"""Export API: site rendering, duplicate-dir guard, default dir, 404s."""

import io
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

TTL = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
"""


def _upload(client: TestClient) -> str:
    """Upload the mini ontology; return its id."""
    r = client.post("/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(TTL), "text/turtle")})
    assert r.status_code == 201
    return r.json()["data"]["id"]


def test_export_site_happy_path(client: TestClient, tmp_path: Path) -> None:
    """Export to an explicit dir: camelCase payload, index.html + entity pages on disk."""
    oid = _upload(client)
    out = tmp_path / "site"
    r = client.post(f"/api/ontologies/{oid}/export/site", json={"out_dir": str(out)})
    body = r.json()
    assert r.status_code == 200
    assert body["code"] == "OK"
    assert set(body["data"]) == {"outputDir", "pageCount"}
    assert body["data"]["outputDir"] == str(out)
    assert body["data"]["pageCount"] == 3  # index + two classes
    assert (out / "index.html").is_file()
    assert len(list((out / "entities").glob("*.html"))) == 2


def test_export_duplicate_dir_guard(client: TestClient, tmp_path: Path) -> None:
    """Re-export into the non-empty dir is VALIDATION_ERROR unless force clears it."""
    oid = _upload(client)
    out = tmp_path / "site"
    first = client.post(f"/api/ontologies/{oid}/export/site", json={"outDir": str(out)})
    assert first.status_code == 200

    again = client.post(f"/api/ontologies/{oid}/export/site", json={"outDir": str(out)})
    assert again.status_code == 422
    assert again.json()["code"] == "VALIDATION_ERROR"
    assert again.json()["hint"]

    forced = client.post(
        f"/api/ontologies/{oid}/export/site", json={"outDir": str(out), "force": True}
    )
    assert forced.status_code == 200
    assert forced.json()["data"]["pageCount"] == 3


def test_export_default_dir_sample_site(client: TestClient, tmp_path: Path) -> None:
    """No outDir: default under {data_dir}/exports; pizza sample yields a full site.

    Headless stand-in for the manual UI smoke (Step 3): exporting the pizza
    sample must produce a valid site with an index page and entity pages.
    """
    oid = client.post("/api/samples/pizza").json()["data"]["id"]
    r = client.post(f"/api/ontologies/{oid}/export/site", json={})
    assert r.status_code == 200
    data = r.json()["data"]
    out = Path(data["outputDir"])
    assert str(out).startswith(str(tmp_path / "exports"))
    assert (out / "index.html").is_file()
    entity_pages = list((out / "entities").glob("*.html"))
    assert len(entity_pages) >= 1
    search = json.loads((out / "data" / "index.json").read_text(encoding="utf-8"))
    assert len(search) == data["pageCount"] - 1 == len(entity_pages)


def test_export_unknown_ontology_is_404(client: TestClient) -> None:
    """Unknown and malformed ids collapse to a uniform NOT_FOUND."""
    missing = client.post(f"/api/ontologies/{uuid4()}/export/site", json={})
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"

    malformed = client.post("/api/ontologies/not-a-uuid/export/site", json={})
    assert malformed.status_code == 404
    assert malformed.json()["code"] == "NOT_FOUND"
