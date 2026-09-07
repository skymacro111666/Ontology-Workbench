"""SPARQL query endpoint (M1 read-only console, spec 2026-09-07)."""

import io

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
