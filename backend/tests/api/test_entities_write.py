"""Graph-side entity editing (A2): create classes/properties, edit, delete.

Every write goes through the A1 pipeline shape: baseFileHash optimistic
lock, serialize + reparse validation, atomic file write, row/cache refresh
(design spec 2026-08-26 §4).
"""

import io
from typing import Any

from fastapi.testclient import TestClient

THING = "http://example.org/Thing"
ANIMAL = "http://example.org/Animal"
DOG = "http://example.org/Dog"
TOY = "http://example.org/Toy"
HAS_TOY = "http://example.org/hasToy"

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ;
  rdfs:subClassOf [ a owl:Restriction ; owl:onProperty ex:hasToy ; owl:someValuesFrom ex:Toy ] .
ex:hasToy a owl:ObjectProperty ; rdfs:domain ex:Dog ; rdfs:range ex:Toy .
ex:Toy a owl:Class .
ex:name a owl:DatatypeProperty ; rdfs:domain ex:Dog ; rdfs:range xsd:string .
"""


def _upload(client: TestClient) -> tuple[str, dict[str, Any]]:
    """Upload MINI and return (oid, meta)."""
    r = client.post(
        "/api/ontologies", files={"file": ("mini.ttl", io.BytesIO(MINI), "text/turtle")}
    )
    assert r.status_code == 201
    return r.json()["data"]["id"], r.json()["data"]


def _overview(client: TestClient, oid: str) -> dict[str, Any]:
    """Fetch the canvas overview payload."""
    return client.get(f"/api/ontologies/{oid}/overview").json()["data"]


def _source(client: TestClient, oid: str) -> str:
    """Fetch the stored source text."""
    return client.get(f"/api/ontologies/{oid}/source").json()["data"]["content"]


def test_create_class_with_parent_and_label(client: TestClient) -> None:
    """POST /classes lands the node, the subClassOf edge and a @zh label."""
    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "Cat",
            "prefix": "ex",
            "label": {"value": "猫", "lang": "zh"},
            "comment": "A cat.",
            "parents": [ANIMAL],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["entity"]["curie"] == "ex:Cat"
    assert data["meta"]["classCount"] == meta["classCount"] + 1

    ov = _overview(client, oid)
    assert any(n["curie"] == "ex:Cat" for n in ov["nodes"])
    cat = next(n["id"] for n in ov["nodes"] if n["curie"] == "ex:Cat")
    assert any(e["source"] == cat and e["target"] == ANIMAL for e in ov["edges"])
    # The label lands as a @zh literal and the comment survives round-trip.
    ent = client.get(f"/api/ontologies/{oid}/entities/{cat}").json()["data"]
    assert ent["label"] == {"zh": "猫"}
    assert ent["comment"] == "A cat."
    assert "ex:Cat" in _source(client, oid)


def test_create_object_and_datatype_properties(client: TestClient) -> None:
    """POST /properties wires domain/range edges for both property kinds."""
    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/properties",
        json={
            "name": "playsWith",
            "prefix": "ex",
            "ptype": "ObjectProperty",
            "domains": [DOG],
            "ranges": [TOY],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200
    ov = _overview(client, oid)
    # Domain+range declared → the new direct-edge contract (2026-08-31):
    # playsWith renders as one Dog→Toy objectProperty edge, not a node.
    direct = [
        e
        for e in ov["edges"]
        if e.get("kind") == "objectProperty" and e.get("label") == "playsWith"
    ]
    assert [(e["source"], e["target"]) for e in direct] == [(DOG, TOY)]
    assert not any(n["curie"] == "ex:playsWith" for n in ov["nodes"])

    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.post(
        f"/api/ontologies/{oid}/properties",
        json={
            "name": "age",
            "prefix": "ex",
            "ptype": "DatatypeProperty",
            "domains": [DOG],
            "ranges": ["http://www.w3.org/2001/XMLSchema#integer"],
            "baseFileHash": meta2["fileHash"],
        },
    )
    assert r.status_code == 200
    src = _source(client, oid)
    assert "ex:age" in src and "integer" in src


def test_write_guards_conflict_duplicate_prefix_notfound(client: TestClient) -> None:
    """Stale hash → 409; existing IRI → DUPLICATE_ENTITY; bad prefix → 422."""
    oid, meta = _upload(client)
    dup = {
        "name": "Dog",
        "prefix": "ex",
        "parents": [],
        "baseFileHash": meta["fileHash"],
    }
    r = client.post(f"/api/ontologies/{oid}/classes", json=dup)
    assert r.status_code == 409
    assert r.json()["code"] == "DUPLICATE_ENTITY"

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "X", "prefix": "nope", "parents": [], "baseFileHash": meta["fileHash"]},
    )
    assert r.status_code == 422
    assert "ex" in (r.json()["hint"] or "")

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "X", "prefix": "ex", "parents": [], "baseFileHash": "stale"},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "EDIT_CONFLICT"

    r = client.post(
        "/api/ontologies/00000000-0000-0000-0000-000000000000/classes",
        json={"name": "X", "prefix": "ex", "parents": [], "baseFileHash": "h"},
    )
    assert r.status_code == 404


def test_invalid_iri_refs_are_422_and_file_unchanged(client: TestClient) -> None:
    """Scheme-less/spacey IRIs into parents/domains/ranges are 422, not 500.

    Every gate fires before the first mutation, so the stored file (and its
    hash — the lock token) is byte-identical after each refusal.
    """
    oid, meta = _upload(client)
    before = _source(client, oid)

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "X",
            "prefix": "ex",
            "parents": ["not an iri"],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"

    r = client.post(
        f"/api/ontologies/{oid}/properties",
        json={
            "name": "p",
            "prefix": "ex",
            "ptype": "ObjectProperty",
            "domains": [DOG],
            "ranges": ["example.org/B"],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 422

    r = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={"parents": ["http://exa mple.org/A"], "baseFileHash": meta["fileHash"]},
    )
    assert r.status_code == 422
    assert "absolute IRI" in (r.json()["hint"] or "")

    # Refused everywhere: file untouched, hash still valid for the next write.
    assert _source(client, oid) == before
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    assert meta2["fileHash"] == meta["fileHash"]
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Y", "prefix": "ex", "parents": [], "baseFileHash": meta["fileHash"]},
    )
    assert r.status_code == 200


def test_update_entity_label_comment_parents(client: TestClient) -> None:
    """PUT /entities rewrites label/comment/parents but keeps restrictions."""
    oid, meta = _upload(client)
    r = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={
            "label": {"value": "狗", "lang": "zh"},
            "comment": "Good dog.",
            "parents": [THING],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200
    ent = client.get(f"/api/ontologies/{oid}/entities/{DOG}").json()["data"]
    assert ent["label"] == {"zh": "狗"}
    assert ent["comment"] == "Good dog."
    assert [p["eid"] for p in ent["parents"]] == [THING]
    # The owl:Restriction blank-node axiom survives the reparent.
    assert "Restriction" in _source(client, oid)


def test_update_entity_clears_with_empty_and_404s_on_unknown(client: TestClient) -> None:
    """parents: [] clears named parents; unknown eid is 404."""
    oid, meta = _upload(client)
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.put(
        f"/api/ontologies/{oid}/entities/{ANIMAL}",
        json={"parents": [], "baseFileHash": meta2["fileHash"]},
    )
    assert r.status_code == 200
    ent = client.get(f"/api/ontologies/{oid}/entities/{ANIMAL}").json()["data"]
    assert ent["parents"] == []

    meta3 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.put(
        f"/api/ontologies/{oid}/entities/{'http://example.org/Ghost'}",
        json={"comment": "x", "baseFileHash": meta3["fileHash"]},
    )
    assert r.status_code == 404


def test_delete_entity_prunes_reverse_references(client: TestClient) -> None:
    """DELETE removes the entity and (prune) every edge pointing at it."""
    oid, meta = _upload(client)
    r = client.delete(
        f"/api/ontologies/{oid}/entities/{ANIMAL}?baseFileHash={meta['fileHash']}&prune=true"
    )
    assert r.status_code == 200
    ov = _overview(client, oid)
    assert all(n["id"] != ANIMAL for n in ov["nodes"])
    src = _source(client, oid)
    assert "ex:Animal" not in src


def test_delete_keeps_dangling_references_without_prune(client: TestClient) -> None:
    """prune=false leaves reverse triples in the file."""
    oid, meta = _upload(client)
    r = client.delete(
        f"/api/ontologies/{oid}/entities/{ANIMAL}?baseFileHash={meta['fileHash']}&prune=false"
    )
    assert r.status_code == 200
    src = _source(client, oid)
    # Dog's subClassOf → Animal survives as a dangling reference.
    assert "ex:Animal" in src


def test_entity_write_refreshes_disk_ir_cache(client: TestClient, monkeypatch) -> None:
    """After a class create, a dropped memory cache serves without re-parse.

    The freshness matters as much as existence: _persist updated file_hash,
    so a stale pkl would miss and the spy below would record a parse.
    """
    import ontoworkbench.server.routers.browse as browse_mod

    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "Cat",
            "prefix": "ex",
            "parents": [ANIMAL],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200

    client.app.state.cache.drop(oid)
    calls = []
    real = browse_mod.timed_parse_store

    def spy(data, fmt):  # noqa: ANN001 — test-local shape
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(browse_mod, "timed_parse_store", spy)
    ov = client.get(f"/api/ontologies/{oid}/overview")
    assert ov.status_code == 200
    assert ov.json()["data"]["totalCount"] == 7  # MINI 6 entities + Cat
    assert calls == []


def test_edit_parses_file_once_and_keeps_parse_ms(client: TestClient, monkeypatch) -> None:
    """An edit parses the file exactly once.

    cache.load_store is the only parse; the _persist re-parse is gone.
    stats_json keeps the old parse_ms and gains build_ms.
    """
    from uuid import UUID

    import ontoworkbench.server.cache as cache_mod
    from ontoworkbench.db.models import Ontology
    from ontoworkbench.db.session import sessionmaker_or_fail

    oid, meta = _upload(client)
    calls: list[int] = []
    real = cache_mod.parse_store

    def spy(data, fmt):  # noqa: ANN001 — test-local shape
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(cache_mod, "parse_store", spy)
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "Cat",
            "prefix": "ex",
            "parents": [ANIMAL],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200, r.text
    assert calls == [1]  # load_store only; the _persist re-parse is gone

    after = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    assert after["parseMs"] == meta["parseMs"]  # kept from the original parse
    with sessionmaker_or_fail()() as session:
        row = session.get(Ontology, UUID(oid))
        assert row is not None
        assert row.stats_json["build_ms"] is not None  # new key
    assert "ow_build_seconds" in client.get("/metrics").text


RDFXML_DEFAULT_NS = b"""<?xml version="1.0"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://example.org/"
         xmlns:owl="http://www.w3.org/2002/07/owl#">
  <owl:Class rdf:about="http://example.org/Thing"/>
  <owl:Class rdf:about="http://example.org/Animal"/>
</rdf:RDF>
"""


EMPTY_PREFIX_TTL = b"""@prefix : <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
:Thing a owl:Class .
"""


def test_create_class_in_default_namespace(client: TestClient) -> None:
    """An empty prefix mints in the declared default namespace (pizza-style).

    The rdflib era allowed default-namespace creation (`@prefix :`); the
    migration lost it to a 422 "Unknown prefix" until PrefixMap captured
    the empty prefix.
    """
    r = client.post(
        "/api/ontologies",
        files={"file": ("pizza.ttl", io.BytesIO(EMPTY_PREFIX_TTL), "text/turtle")},
    )
    assert r.status_code == 201
    oid, meta = r.json()["data"]["id"], r.json()["data"]

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Cat", "prefix": "", "parents": [], "baseFileHash": meta["fileHash"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["entity"] == {
        "eid": "http://example.org/Cat",
        "curie": ":Cat",
        "type": "Class",
    }

    # The dumped file keeps the default prefix bound and re-parses cold
    client.app.state.cache.drop(oid)
    ov = _overview(client, oid)
    assert any(n["id"] == "http://example.org/Cat" and n["curie"] == ":Cat" for n in ov["nodes"])
    assert ":Cat a owl:Class" in _source(client, oid)


def test_edit_rdfxml_default_namespace_round_trips(client: TestClient) -> None:
    """An edit on rdfxml with a default xmlns keeps it through the dump.

    The empty-prefix declaration flows PrefixMap.as_dict() → store.dump
    prefixes: the rewritten file must still parse and keep the default
    namespace bound (2026-09-03 plan carry-in).
    """
    r = client.post(
        "/api/ontologies",
        files={"file": ("mini.rdf", io.BytesIO(RDFXML_DEFAULT_NS), "application/rdf+xml")},
    )
    assert r.status_code == 201
    oid, meta = r.json()["data"]["id"], r.json()["data"]

    r = client.put(
        f"/api/ontologies/{oid}/entities/{THING}",
        json={"comment": "root", "baseFileHash": meta["fileHash"]},
    )
    assert r.status_code == 200, r.text

    src = _source(client, oid)
    assert 'xmlns="http://example.org/"' in src  # default namespace survives
    # The dumped file re-parses: a second edit on the refreshed hash works.
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.put(
        f"/api/ontologies/{oid}/entities/{ANIMAL}",
        json={"comment": "child", "baseFileHash": meta2["fileHash"]},
    )
    assert r.status_code == 200, r.text
    assert "child" in _source(client, oid)


JSONLD_CONTEXT = b"""{
  "@context": {
    "ex": "http://example.org/",
    "owl": "http://www.w3.org/2002/07/owl#"
  },
  "@id": "ex:Thing",
  "@type": "owl:Class"
}"""


def test_edit_jsonld_round_trips(client: TestClient) -> None:
    """Creating a class in a jsonld ontology survives the dump + re-parse."""
    r = client.post(
        "/api/ontologies",
        files={"file": ("mini.jsonld", io.BytesIO(JSONLD_CONTEXT), "application/ld+json")},
    )
    assert r.status_code == 201
    oid, meta = r.json()["data"]["id"], r.json()["data"]

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Cat", "prefix": "ex", "baseFileHash": meta["fileHash"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["entity"]["curie"] == "ex:Cat"

    # Force the cold path: the dumped file must re-parse and serve the edit.
    client.app.state.cache.drop(oid)
    ov = _overview(client, oid)
    assert any(n["id"] == "http://example.org/Cat" for n in ov["nodes"])
