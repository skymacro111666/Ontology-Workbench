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
    """Property rendering per the 2026-08-31 revision.

    An object property with declared domain+range is ONE direct class→class
    edge (objectProperty, domain→range, labeled with the local name);
    datatype properties keep node form carrying ptype so the canvas filter
    can split them.
    """
    oid = _upload_props(client)
    ov = client.get(f"/api/ontologies/{oid}/overview").json()["data"]
    curies = {n["curie"] for n in ov["nodes"]}
    assert "ex:livesIn" not in curies  # domain Animal + range Thing → edge
    direct = [e for e in ov["edges"] if e["kind"] == "objectProperty"]
    assert [(e["source"], e["target"], e["label"]) for e in direct] == [
        ("http://example.org/Animal", "http://example.org/Thing", "livesIn")
    ]
    ptypes = {n["curie"]: n.get("ptype") for n in ov["nodes"]}
    assert ptypes["ex:age"] == "DatatypeProperty"
    assert ptypes["ex:Dog"] is None


def test_source_endpoint_serves_raw_file(client: TestClient) -> None:
    """GET /source serves the stored file verbatim (text view data)."""
    oid = _upload(client)
    src = client.get(f"/api/ontologies/{oid}/source").json()["data"]
    assert src["filename"] == "mini.ttl"
    assert src["format"] == "turtle"
    # Verbatim upload bytes — prefixes and triples round-trip untouched.
    assert src["content"] == MINI.decode()


def test_source_unknown_ontology_is_404(client: TestClient) -> None:
    """A random UUID yields the uniform NOT_FOUND envelope."""
    import uuid

    r = client.get(f"/api/ontologies/{uuid.uuid4()}/source")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


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


def test_entity_endpoint_dispatches_instance(client: TestClient) -> None:
    """GET /entities/{eid} 对实例返回 kind=instance 载荷;search 支持 type 过滤."""
    oid = _upload_library(client)
    eid = quote(
        "https://github.com/skymacro111666/ontology-workbench/samples/library#ThreeBody",
        safe="",
    )
    r = client.get(f"/api/ontologies/{oid}/entities/{eid}")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["kind"] == "instance"
    assert data["curie"] == "lib:ThreeBody"
    assert any(a["object"]["curie"] == "lib:LiuCixin" for a in data["objectAssertions"])
    assert any(a["value"] == "2008" for a in data["dataAssertions"])

    r = client.get(f"/api/ontologies/{oid}/search", params={"q": "three", "type": "instance"})
    hits = r.json()["data"]
    assert len(hits) == 2  # ThreeBody and ThreeBodyAudiobook both match
    assert all(h["type"] == "Instance" for h in hits)

    # Regression test: first-letter normalization preserves camelCase.
    # (ObjectProperty not Objectproperty - capitalize() would mangle).
    r = client.get(
        f"/api/ontologies/{oid}/search",
        params={"q": "located", "type": "ObjectProperty"},
    )
    hits = r.json()["data"]
    assert len(hits) == 1
    assert hits[0]["type"] == "ObjectProperty"


def _upload_library(client: TestClient) -> str:
    """Upload the bundled library sample; returns oid."""
    from pathlib import Path

    data = (Path(__file__).parents[2] / "ontoworkbench" / "samples" / "library.ttl").read_bytes()
    r = client.post(
        "/api/ontologies", files={"file": ("library.ttl", io.BytesIO(data), "text/turtle")}
    )
    assert r.status_code == 201
    return r.json()["data"]["id"]


def test_assertion_schema_closure_and_domainless(client: TestClient) -> None:
    """Novel 的 schema 含自身 domain 属性;继承与无 domain 属性并入."""
    from urllib.parse import quote

    # 引号拼进 URL(引 IRI 走线上一重编码;params= 会把 % 再编码一次)
    oid = _upload_library(client)
    cls = quote(
        "https://github.com/skymacro111666/ontology-workbench/samples/library#ScienceFiction",
        safe="",
    )
    r = client.get(f"/api/ontologies/{oid}/assertion-schema?classes={cls}")
    assert r.status_code == 200
    props = {p["curie"]: p for p in r.json()["data"]}
    assert "lib:hasCreator" in props  # domain 覆盖(含父类闭包或直接)
    for p in r.json()["data"]:
        assert p["ptype"] in ("ObjectProperty", "DatatypeProperty", "Property")


def test_assertion_edges_only_between_given(client: TestClient) -> None:
    """给定集合内的对象断言成边;集合外的不画."""
    from urllib.parse import quote

    oid = _upload_library(client)
    tb, lx = (
        quote(
            "https://github.com/skymacro111666/ontology-workbench/samples/library#ThreeBody",
            safe="",
        ),
        quote(
            "https://github.com/skymacro111666/ontology-workbench/samples/library#LiuCixin",
            safe="",
        ),
    )
    r = client.get(f"/api/ontologies/{oid}/assertion-edges?eids={tb},{lx}")
    assert r.status_code == 200
    edges = r.json()["data"]["edges"]
    assert any(e["label"] == "hasCreator" for e in edges)
    # 只给 ThreeBody:断言对象不在集合 → 无边
    r = client.get(f"/api/ontologies/{oid}/assertion-edges?eids={tb}")
    assert r.json()["data"]["edges"] == []


def test_browse_serves_from_disk_ir_cache_after_memory_drop(
    client: TestClient, monkeypatch
) -> None:
    """A dropped memory cache (restart stand-in) re-serves via index.pkl.

    Flow: upload → drop → GET (miss: parses once, write-through) → drop →
    GET under a parse spy (hit: served from disk, zero parses).
    """
    import ontoworkbench.server.routers.browse as browse_mod

    oid = _upload(client)
    client.app.state.cache.drop(oid)
    first = client.get(f"/api/ontologies/{oid}/tree")
    assert first.status_code == 200

    client.app.state.cache.drop(oid)
    calls = []
    real = browse_mod.parse_graph

    def spy(data, fmt):  # noqa: ANN001 — test-local shape
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(browse_mod, "parse_graph", spy)
    second = client.get(f"/api/ontologies/{oid}/tree")
    assert second.status_code == 200
    assert second.json()["data"][0]["curie"] == "ex:Thing"
    assert calls == []  # disk cache hit — the file was never re-parsed

    metrics = client.get("/metrics").text
    assert 'ow_ir_cache_reads_total{result="hit"}' in metrics


def test_upload_warms_disk_ir_cache(client: TestClient, monkeypatch) -> None:
    """The very first post-restart read serves from pkl: upload wrote it."""
    import ontoworkbench.server.routers.browse as browse_mod

    oid = _upload(client)
    client.app.state.cache.drop(oid)
    calls = []
    real = browse_mod.parse_graph

    def spy(data, fmt):  # noqa: ANN001 — test-local shape
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(browse_mod, "parse_graph", spy)
    tree = client.get(f"/api/ontologies/{oid}/tree")
    assert tree.status_code == 200
    assert calls == []


def test_browse_records_build_metric(client: TestClient) -> None:
    """ow_build_seconds appears on /metrics after a cold browse."""
    oid = _upload(client)
    client.app.state.cache.drop(oid)
    assert client.get(f"/api/ontologies/{oid}/tree").status_code == 200
    assert "ow_build_seconds" in client.get("/metrics").text
