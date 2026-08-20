"""Read APIs over an uploaded mini ontology."""

import io
from urllib.parse import quote

from fastapi.testclient import TestClient

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing ; rdfs:comment "alive"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "Dog"@en .
"""


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
    assert ov["totalCount"] == 3 and ov["truncated"] is False


def test_browse_payloads_are_camelcase(client: TestClient) -> None:
    """Golden-contract casing: browse data keys serialize as camelCase."""
    oid = _upload(client)
    tree = client.get(f"/api/ontologies/{oid}/tree").json()["data"]
    assert tree[0]["childrenCount"] == 1
    assert "children_count" not in tree[0]

    eid = quote("http://example.org/Animal", safe="")
    ent = client.get(f"/api/ontologies/{oid}/entities/{eid}").json()["data"]
    assert ent["stats"]["directChildren"] == 1
    assert "referencedBy" in ent
    assert "referenced_by" not in ent
    assert "direct_children" not in ent["stats"]

    hits = client.get(f"/api/ontologies/{oid}/search?q=dog").json()["data"]
    assert "matchedField" in hits[0]
    assert "matched_field" not in hits[0]

    ov = client.get(f"/api/ontologies/{oid}/overview").json()["data"]
    assert ov["totalCount"] == 3
    assert "total_count" not in ov


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


def test_foreign_owner_ontology_is_404(client: TestClient) -> None:
    """An ontology owned by another user is indistinguishable from missing."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ontoworkbench.auth.password import hash_password
    from ontoworkbench.db.models import Base, Ontology
    from ontoworkbench.db.repositories import UserRepository

    # Second user created directly (the public API is single-admin Phase 1).
    app = client.app
    db_url = app.state.settings.db_url
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    other = UserRepository(session).create("intruder", hash_password("long-enough-pw"))
    row = Ontology(
        owner_user_id=other.id,
        filename="foreign.ttl",
        storage_path="/tmp/foreign.ttl",
        format="turtle",
        file_size_bytes=1,
        file_hash="x",
        class_count=0,
        property_count=0,
        axiom_count=0,
    )
    session.add(row)
    session.commit()
    foreign_id = str(row.id)
    session.close()

    r = client.get(f"/api/ontologies/{foreign_id}/tree")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


def test_search_limit_must_be_positive(client: TestClient) -> None:
    """limit=0 is a validation error, not a one-hit answer."""
    oid = _upload(client)
    r = client.get(f"/api/ontologies/{oid}/search", params={"q": "dog", "limit": 0})
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"
