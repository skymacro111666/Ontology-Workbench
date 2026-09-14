"""SPARQL query endpoint (M1 read-only console, spec 2026-09-07)."""

import io

import pytest
from fastapi.testclient import TestClient

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing ; rdfs:label "Animal"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
"""


def _upload(client: TestClient) -> str:
    r = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(MINI), "text/turtle")}
    )
    return r.json()["data"]["id"]


def _run(client: TestClient, oid: str, qs: str):
    return client.post(f"/api/ontologies/{oid}/query", json={"qs": qs}).json()["data"]


def test_select_with_path_and_curie(client: TestClient) -> None:
    """SELECT: property-path descendants reach the class; IRIs shorten to curies."""
    oid = _upload(client)
    data = _run(
        client,
        oid,
        """PREFIX ex: <http://example.org/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?d WHERE { ?d rdfs:subClassOf+ ex:Thing } ORDER BY ?d""",
    )
    assert data["kind"] == "select"
    assert data["columns"] == ["d"]
    assert data["rowCount"] == 2 and data["truncated"] is False
    cells = [r["d"]["curie"] for r in data["rows"]]
    assert cells == ["ex:Animal", "ex:Dog"]
    assert data["rows"][0]["d"]["type"] == "iri"
    assert data["elapsedMs"] >= 0


def test_select_literal_terms(client: TestClient) -> None:
    """Literal cells carry value plus language/datatype metadata."""
    oid = _upload(client)
    data = _run(
        client,
        oid,
        """PREFIX ex: <http://example.org/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        SELECT ?l WHERE { ex:Dog rdfs:label ?l }""",
    )
    lit = data["rows"][0]["l"]
    assert lit["type"] == "literal" and lit["value"] == "Dog" and lit["language"] == "en"


def test_ask_shape(client: TestClient) -> None:
    """ASK returns a boolean payload."""
    oid = _upload(client)
    yes = _run(client, oid, "ASK { ?s ?p ?o }")
    no = _run(client, oid, "ASK { <http://example.org/Ghost> ?p ?o }")
    assert yes["kind"] == "ask" and yes["boolean"] is True
    assert no["boolean"] is False


def test_construct_serializes_turtle(client: TestClient) -> None:
    """CONSTRUCT/DESCRIBE return capped turtle text."""
    oid = _upload(client)
    data = _run(
        client,
        oid,
        "CONSTRUCT { ?d <http://example.org/under> <http://example.org/Thing> } "
        "WHERE { ?d <http://www.w3.org/2000/01/rdf-schema#subClassOf>+ "
        "<http://example.org/Thing> }",
    )
    assert data["kind"] == "construct"
    assert data["tripleCount"] == 2 and data["truncated"] is False
    assert "<http://example.org/Animal> <http://example.org/under>" in data["turtle"]


def test_update_rejected_as_invalid(client: TestClient) -> None:
    """SPARQL UPDATE never runs: engine-level read-only via query()."""
    oid = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/query",
        json={"qs": "INSERT DATA { <http://x/a> <http://x/b> <http://x/c> }"},
    )
    assert r.status_code == 400
    assert r.json()["code"] == "QUERY_INVALID"
    # Nothing landed: the class count did not change.
    tree = client.get(f"/api/ontologies/{oid}/tree").json()["data"]
    assert len(tree) == 1


def test_syntax_garbage_is_query_invalid(client: TestClient) -> None:
    """Non-SPARQL text 400s with the engine's parse message as hint."""
    oid = _upload(client)
    r = client.post(f"/api/ontologies/{oid}/query", json={"qs": "NONSENSE {"})
    assert r.status_code == 400 and r.json()["code"] == "QUERY_INVALID"


def test_row_cap_truncates_truthfully(client: TestClient, monkeypatch) -> None:
    """Rows cap at MAX_QUERY_ROWS; truncated flags the cut."""
    import ontoworkbench.server.routers.query as q

    monkeypatch.setattr(q, "MAX_QUERY_ROWS", 1)
    oid = _upload(client)
    data = _run(
        client,
        oid,
        "SELECT ?s WHERE { ?s ?p ?o }",
    )
    assert data["rowCount"] == 1 and data["truncated"] is True


def test_query_requires_owned_ontology(client: TestClient) -> None:
    """Foreign/unknown oid 404s like every other browse endpoint."""
    r = client.post(
        "/api/ontologies/00000000-0000-0000-0000-000000000000/query",
        json={"qs": "SELECT * WHERE { ?s ?p ?o }"},
    )
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


# --- POST /query/export (2026-09-14: CSV/JSON 全量导出,安全上限+截断提示) ---

SELECT_ALL = "SELECT ?s ?p ?o WHERE { ?s ?p ?o } ORDER BY ?s ?p ?o"


def _export(client: TestClient, oid: str, qs: str, format: str = "csv"):
    return client.post(f"/api/ontologies/{oid}/query/export", json={"qs": qs, "format": format})


def test_export_select_csv(client: TestClient) -> None:
    """CSV: BOM + variable-named header + one row per solution, full IRIs."""
    oid = _upload(client)
    r = _export(client, oid, SELECT_ALL)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="mini-query.csv"' in r.headers["content-disposition"]
    assert r.headers.get("x-truncated") is None  # 只有真截断才带
    assert r.content.startswith(b"\xef\xbb\xbf")
    lines = r.content.decode("utf-8").splitlines()
    assert lines[0] == "﻿s,p,o"
    assert len(lines) == 8  # header + 7 triples(MINI:2+3+3)
    assert any("http://example.org/Animal" in ln for ln in lines)


def test_export_select_json_rich_cells(client: TestClient) -> None:
    """JSON: same shape as /query — typed cells with curie/lang metadata."""
    oid = _upload(client)
    r = _export(client, oid, SELECT_ALL, format="json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert 'filename="mini-query.json"' in r.headers["content-disposition"]
    d = r.json()  # 文件下载绕过 envelope
    assert d["kind"] == "select" and d["columns"] == ["s", "p", "o"]
    assert d["rowCount"] == 7 and d["truncated"] is False and d["rowLimit"] == 500000
    cell = next(row["s"] for row in d["rows"] if row["s"] and row["s"].get("curie") == "ex:Animal")
    assert cell["type"] == "iri" and cell["value"] == "http://example.org/Animal"


def test_export_truncation_marks_everywhere(client: TestClient, monkeypatch) -> None:
    """Over the cap every channel says so.

    JSON truncated+rowCount capped, CSV trailing marker, X-Truncated
    header — the user must never miss that data was held back.
    """
    import ontoworkbench.server.routers.query as q

    monkeypatch.setattr(q, "MAX_QUERY_EXPORT_ROWS", 5)
    oid = _upload(client)
    rj = _export(client, oid, SELECT_ALL, format="json")
    d = rj.json()
    assert d["truncated"] is True and d["rowCount"] == 5 and d["rowLimit"] == 5
    assert rj.headers["x-truncated"] == "true"
    rc = _export(client, oid, SELECT_ALL)
    lines = rc.content.decode("utf-8").splitlines()
    assert len(lines) == 1 + 5 + 1  # header + rows + marker
    assert lines[-1].startswith("#TRUNCATED") and "5" in lines[-1]
    assert rc.headers["x-truncated"] == "true"


def test_export_non_select_is_400(client: TestClient) -> None:
    """ASK/CONSTRUCT have no spreadsheet export: 400 EXPORT_SELECT_ONLY."""
    oid = _upload(client)
    r = _export(client, oid, "ASK { ?s ?p ?o }")
    assert r.status_code == 400 and r.json()["code"] == "EXPORT_SELECT_ONLY"
    r2 = _export(client, oid, "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }")
    assert r2.status_code == 400 and r2.json()["code"] == "EXPORT_SELECT_ONLY"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
def test_export_invalid_query_keeps_400_query_invalid(client: TestClient) -> None:
    """UPDATE garbage maps to the same code as /query."""
    oid = _upload(client)
    r = _export(client, oid, "DELETE WHERE { ?s ?p ?o }")
    assert r.status_code == 400 and r.json()["code"] == "QUERY_INVALID"


def test_export_rejects_unknown_format(client: TestClient) -> None:
    """Format is Literal[csv, json]: anything else is a 422."""
    oid = _upload(client)
    r = _export(client, oid, SELECT_ALL, format="xml")
    assert r.status_code == 422
