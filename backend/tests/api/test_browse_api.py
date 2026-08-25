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


MINI_PROPS = (
    MINI
    + b"""ex:livesIn a owl:ObjectProperty ; rdfs:domain ex:Animal ;
rdfs:range ex:Thing .
ex:age a owl:DatatypeProperty ; rdfs:domain ex:Dog .
"""
)


def _upload_props(client: TestClient) -> str:
    r = client.post(
        "/api/ontologies",
        files={"file": ("mini-props.ttl", io.BytesIO(MINI_PROPS), "text/turtle")},
    )
    return r.json()["data"]["id"]


def test_tree_props_sentinel(client: TestClient) -> None:
    """tree?parent=__props__ lists property nodes with their type (PropList source)."""
    oid = _upload_props(client)
    props = client.get(f"/api/ontologies/{oid}/tree", params={"parent": "__props__"}).json()["data"]
    assert [p["curie"] for p in props] == ["ex:age", "ex:livesIn"]
    assert {p["type"] for p in props} == {"ObjectProperty", "DatatypeProperty"}
    assert all(p["childrenCount"] == 0 for p in props)
    # The class tree is unaffected by the sentinel branch.
    roots = client.get(f"/api/ontologies/{oid}/tree").json()["data"]
    assert all(n["type"] == "Class" for n in roots)


def test_meta_endpoint(client: TestClient) -> None:
    """GET /meta serves the browse page's metadata (counts + prefixes), owner-checked."""
    oid = _upload_props(client)
    meta = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    assert meta["filename"] == "mini-props.ttl"
    assert meta["classCount"] == 3
    assert meta["propertyCount"] == 2
    assert meta["prefixes"]["ex"] == "http://example.org/"
    assert "owl" in meta["prefixes"]


MINI_INST = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Animal a owl:Class .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal .
ex:rex a owl:NamedIndividual , ex:Dog ; rdfs:label "Rex"@en .
ex:buddy a owl:NamedIndividual , ex:Dog .
"""


def test_instances_endpoint(client: TestClient) -> None:
    """GET entities/{eid}/instances serves canvas-shaped instance data."""
    r = client.post(
        "/api/ontologies",
        files={"file": ("inst.ttl", io.BytesIO(MINI_INST), "text/turtle")},
    )
    oid = r.json()["data"]["id"]
    eid = quote("http://example.org/Dog", safe="")

    data = client.get(f"/api/ontologies/{oid}/entities/{eid}/instances").json()["data"]
    assert [n["curie"] for n in data["nodes"]] == ["ex:buddy", "ex:rex"]
    assert all(n["kind"] == "instance" for n in data["nodes"])
    assert data["edges"][0] == {
        "source": "http://example.org/buddy",
        "target": "http://example.org/Dog",
        "kind": "instance",
    }

    # The overview badge count serializes camelCase.
    ov = client.get(f"/api/ontologies/{oid}/overview").json()["data"]
    dog = next(n for n in ov["nodes"] if n["curie"] == "ex:Dog")
    assert dog["instanceCount"] == 2
    assert "instance_count" not in dog

    # The sidebar tree badge serializes the same count camelCase.
    kids = client.get(
        f"/api/ontologies/{oid}/tree", params={"parent": "http://example.org/Animal"}
    ).json()["data"]
    assert kids[0]["instanceCount"] == 2
    assert "instance_count" not in kids[0]


def test_overview_property_nodes_carry_ptype(client: TestClient) -> None:
    """Overview property nodes carry ptype so the canvas filter can split them."""
    oid = _upload_props(client)
    ov = client.get(f"/api/ontologies/{oid}/overview").json()["data"]
    ptypes = {n["curie"]: n.get("ptype") for n in ov["nodes"]}
    assert ptypes["ex:livesIn"] == "ObjectProperty"
    assert ptypes["ex:age"] == "DatatypeProperty"
    assert ptypes["ex:Dog"] is None


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
