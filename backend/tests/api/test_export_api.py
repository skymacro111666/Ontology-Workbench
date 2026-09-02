"""Export API: site rendering, file re-serialization, duplicate-dir guard, 404s."""

import io
import json
import zipfile
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
    """Export to an explicit dir under exports: index.html + entity pages on disk."""
    oid = _upload(client)
    out = tmp_path / "exports" / "site"
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
    out = tmp_path / "exports" / "site"
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


def test_export_site_out_dir_must_stay_under_exports(client: TestClient, tmp_path: Path) -> None:
    """Explicit outDir outside {data_dir}/exports is rejected, target untouched."""
    oid = _upload(client)
    out = tmp_path / "elsewhere"
    r = client.post(f"/api/ontologies/{oid}/export/site", json={"outDir": str(out)})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert "OW_EXPORT_ALLOW_ANY_PATH" in r.json()["hint"]
    assert not out.exists()


def test_export_site_out_dir_inside_exports_ok(client: TestClient, tmp_path: Path) -> None:
    """An explicit outDir under {data_dir}/exports works without the flag."""
    oid = _upload(client)
    out = tmp_path / "exports" / "my-site"
    r = client.post(f"/api/ontologies/{oid}/export/site", json={"outDir": str(out)})
    assert r.status_code == 200
    assert r.json()["data"]["outputDir"] == str(out)
    assert (out / "index.html").is_file()


def test_export_site_rejects_dot_dot_and_symlink_escape(client: TestClient, tmp_path: Path) -> None:
    """Traversal spellings that resolve outside exports are rejected too."""
    oid = _upload(client)
    dots = client.post(
        f"/api/ontologies/{oid}/export/site",
        json={"outDir": str(tmp_path / "exports" / ".." / "escape")},
    )
    assert dots.status_code == 422

    victim = tmp_path / "victim"
    victim.mkdir()
    (tmp_path / "exports").mkdir(exist_ok=True)
    (tmp_path / "exports" / "link").symlink_to(victim)
    link = client.post(
        f"/api/ontologies/{oid}/export/site",
        json={"outDir": str(tmp_path / "exports" / "link")},
    )
    assert link.status_code == 422
    assert list(victim.iterdir()) == []  # untouched, not force-cleared


def test_export_site_any_path_with_flag(client: TestClient, tmp_path: Path) -> None:
    """OW_EXPORT_ALLOW_ANY_PATH=1 relaxes the containment for self-hosted use."""
    client.app.state.settings.export_allow_any_path = True
    oid = _upload(client)
    out = tmp_path / "elsewhere"
    r = client.post(f"/api/ontologies/{oid}/export/site", json={"outDir": str(out)})
    assert r.status_code == 200
    assert (out / "index.html").is_file()


def test_export_unknown_ontology_is_404(client: TestClient) -> None:
    """Unknown and malformed ids collapse to a uniform NOT_FOUND."""
    missing = client.post(f"/api/ontologies/{uuid4()}/export/site", json={})
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"

    malformed = client.post("/api/ontologies/not-a-uuid/export/site", json={})
    assert malformed.status_code == 404
    assert malformed.json()["code"] == "NOT_FOUND"


def test_export_file_reserializes_all_three_formats(client: TestClient) -> None:
    """GET export/file converts the stored turtle into each target format."""
    oid = _upload(client)

    ttl = client.get(f"/api/ontologies/{oid}/export/file", params={"format": "turtle"})
    assert ttl.status_code == 200
    assert ttl.json()["data"]["filename"] == "mini.ttl"
    assert ttl.json()["data"]["mediaType"] == "text/turtle"
    assert "ex:A" in ttl.json()["data"]["content"]

    jsonld = client.get(f"/api/ontologies/{oid}/export/file", params={"format": "json-ld"})
    assert jsonld.status_code == 200
    assert jsonld.json()["data"]["filename"] == "mini.jsonld"
    # Round-trip: the JSON-LD payload parses back and still carries both classes.
    graph = json.loads(jsonld.json()["data"]["content"])
    ids = {e["@id"] for e in graph}
    assert {"http://example.org/A", "http://example.org/B"} <= ids

    rdf = client.get(f"/api/ontologies/{oid}/export/file", params={"format": "rdf-xml"})
    assert rdf.status_code == 200
    assert rdf.json()["data"]["filename"] == "mini.rdf"
    assert "<rdf:RDF" in rdf.json()["data"]["content"]


def test_export_file_rejects_unknown_format(client: TestClient) -> None:
    """An unknown format is VALIDATION_ERROR with the choices as hint."""
    oid = _upload(client)
    r = client.get(f"/api/ontologies/{oid}/export/file", params={"format": "n3"})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"
    assert "turtle" in r.json()["hint"]

    missing = client.get(f"/api/ontologies/{uuid4()}/export/file", params={"format": "turtle"})
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


def test_archive_streams_zip_of_exported_site(client: TestClient, tmp_path: Path) -> None:
    """GET export/site/archive zips a prior export as an attachment."""
    oid = _upload(client)
    out = tmp_path / "exports" / "site"
    client.post(f"/api/ontologies/{oid}/export/site", json={"outDir": str(out)})

    r = client.get(f"/api/ontologies/{oid}/export/site/archive", params={"dir_path": str(out)})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    assert "attachment" in r.headers.get("content-disposition", "")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "index.html" in names
    assert "site.js" in names


def test_archive_rejects_paths_outside_exports(client: TestClient, tmp_path: Path) -> None:
    """dir_path outside {data_dir}/exports is VALIDATION_ERROR, same as POST."""
    oid = _upload(client)
    r = client.get(
        f"/api/ontologies/{oid}/export/site/archive",
        params={"dir_path": str(tmp_path / "elsewhere")},
    )
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_archive_unknown_dir_is_404(client: TestClient, tmp_path: Path) -> None:
    """A dir under exports that was never exported to is a uniform 404."""
    oid = _upload(client)
    ghost = tmp_path / "exports" / "ghost"
    r = client.get(f"/api/ontologies/{oid}/export/site/archive", params={"dir_path": str(ghost)})
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"
