"""Read APIs over an uploaded mini ontology."""

import io
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine
from ontoworkbench.server.app import create_app

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing ; rdfs:comment "alive"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
"""


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Authenticated client with one uploaded mini ontology; yields (client, oid)."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    app = create_app(
        Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "data_dir": tmp_path})
    )
    c = TestClient(app)
    c.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = c.post("/api/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    c.headers["Authorization"] = f"Bearer {r.json()['data']['token']}"
    return c


def _upload(client: TestClient) -> str:
    r = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(MINI), "text/turtle")}
    )
    return r.json()["data"]["id"]


def test_tree_entity_search_raw(client: TestClient) -> None:
    """Tree roots, entity detail, neighbors, search, raw turtle all serve."""
    oid = _upload(client)
    tree = client.get(f"/api/ontologies/{oid}/tree").json()["data"]
    assert tree[0]["curie"] == "ex:Thing"

    eid = quote("http://example.org/Dog", safe="")
    ent = client.get(f"/api/ontologies/{oid}/entities/{eid}").json()["data"]
    assert ent["curie"] == "ex:Dog"
    assert ent["parents"][0]["curie"] == "ex:Animal"

    nb = client.get(f"/api/ontologies/{oid}/entities/{eid}/neighbors").json()["data"]
    assert any(n["curie"] == "ex:Animal" for n in nb["nodes"])

    hits = client.get(f"/api/ontologies/{oid}/search?q=dog").json()["data"]
    assert hits[0]["curie"] == "ex:Dog"

    raw = client.get(f"/api/ontologies/{oid}/raw/{eid}").json()["data"]
    assert "turtle" in raw and "Dog" in raw["turtle"]

    ov = client.get(f"/api/ontologies/{oid}/overview").json()["data"]
    assert ov["total_count"] == 3 and ov["truncated"] is False


def test_tree_lazy_children(client: TestClient) -> None:
    """tree?parent= returns the children of the given entity."""
    oid = _upload(client)
    kids = client.get(
        f"/api/ontologies/{oid}/tree", params={"parent": "http://example.org/Animal"}
    ).json()["data"]
    assert [k["curie"] for k in kids] == ["ex:Dog"]


def test_unknown_ontology_is_404(client: TestClient) -> None:
    """A random UUID yields the uniform NOT_FOUND envelope."""
    import uuid

    r = client.get(f"/api/ontologies/{uuid.uuid4()}/tree")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"
