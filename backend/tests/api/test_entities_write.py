"""Graph-side entity editing (A2): create classes/properties, edit, delete.

Y-axis commit path: every mutation patches the pooled Store + cached IR
under a baseRevision optimistic lock and returns in milliseconds; the
file lands later via the debounced autosave (design spec 2026-09-05).
Tests that read the file wait for the autosave to land first.
"""

import io
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient

from tests.api.conftest import auth, build_app

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


def _wait_landed(client: TestClient, oid: str, timeout: float = 2.0) -> None:
    """Block until the oid's autosave is idle again (file on disk, row fresh).

    schedule() runs inside the handler, so by the time a mutation response
    arrives the state is pending/saving; polling for idle is deterministic
    under the 50ms test debounce (and rides out retry backoffs on failure).
    """
    manager = client.app.state.autosave
    deadline = time.monotonic() + timeout
    while manager.state(oid) != "idle":
        if time.monotonic() > deadline:
            raise AssertionError(f"autosave did not land within {timeout}s")
        time.sleep(0.02)


def test_edit_returns_fast_and_file_lands_later(client: TestClient, autosave_debounce_50ms) -> None:
    """A mutation returns in milliseconds; the file lands on the debounce.

    Read-your-writes: the entity GET right after the response already
    serves the patched IR, before any byte touched the disk.
    """
    oid, meta = _upload(client)
    t0 = time.perf_counter()
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "Fast",
            "prefix": "ex",
            "parents": [],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    assert time.perf_counter() - t0 < 0.5  # milliseconds of work, test-machine margin
    data = r.json()["data"]
    assert data["meta"]["revision"] == 1
    assert data["meta"]["saveState"] == "pending"

    # Read path sees the edit immediately (serves the patched IR).
    ent = client.get(f"/api/ontologies/{oid}/entities/http%3A%2F%2Fexample.org%2FFast")
    assert ent.status_code == 200
    assert ent.json()["data"]["curie"].endswith("Fast")

    _wait_landed(client, oid)
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    assert meta2["saveState"] == "idle"
    assert meta2["revision"] == 1
    assert "ex:Fast" in _source(client, oid)


def test_stale_revision_conflict(client: TestClient, autosave_debounce_50ms) -> None:
    """A baseRevision that lags the row's revision is a 409 on every mutation."""
    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "X", "prefix": "ex", "parents": [], "baseRevision": 7},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "EDIT_CONFLICT"

    r = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={"comment": "x", "baseRevision": 7},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "EDIT_CONFLICT"

    r = client.delete(f"/api/ontologies/{oid}/entities/{DOG}?baseRevision=7")
    assert r.status_code == 409
    assert r.json()["code"] == "EDIT_CONFLICT"

    # The refused edits bumped nothing: revision 0 still admits a legal edit.
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "X", "prefix": "ex", "parents": [], "baseRevision": meta["revision"]},
    )
    assert r.status_code == 200
    assert r.json()["data"]["meta"]["revision"] == 1


def test_shutdown_flushes_pending_edit(tmp_path: Path) -> None:
    """Leaving the app (lifespan shutdown) flushes un-landed edits, zero loss.

    The api client fixture never enters TestClient as a context manager, so
    this test builds its own app: only the with-block fires the lifespan
    (and with it AutosaveManager.flush_all) — under the default 3s debounce
    the edit is still memory-only at that point.
    """
    with TestClient(build_app(tmp_path)) as client:
        auth(client)
        oid, meta = _upload(client)
        r = client.post(
            f"/api/ontologies/{oid}/classes",
            json={
                "name": "Fast",
                "prefix": "ex",
                "parents": [],
                "baseRevision": meta["revision"],
            },
        )
        assert r.status_code == 200
        from ontoworkbench.db.models import Ontology
        from ontoworkbench.db.session import sessionmaker_or_fail

        with sessionmaker_or_fail()() as db:
            row = db.get(Ontology, UUID(oid))
            assert row is not None
            path = Path(row.storage_path)
        assert b"Fast" not in path.read_bytes()  # debounce still pending
    assert b"Fast" in path.read_bytes()  # shutdown flushed the edit to disk


def test_create_class_with_parent_and_label(client: TestClient, autosave_debounce_50ms) -> None:
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
            "baseRevision": meta["revision"],
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
    _wait_landed(client, oid)
    assert "ex:Cat" in _source(client, oid)


def test_create_object_and_datatype_properties(client: TestClient, autosave_debounce_50ms) -> None:
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
            "baseRevision": meta["revision"],
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

    _wait_landed(client, oid)
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.post(
        f"/api/ontologies/{oid}/properties",
        json={
            "name": "age",
            "prefix": "ex",
            "ptype": "DatatypeProperty",
            "domains": [DOG],
            "ranges": ["http://www.w3.org/2001/XMLSchema#integer"],
            "baseRevision": meta2["revision"],
        },
    )
    assert r.status_code == 200
    _wait_landed(client, oid)
    src = _source(client, oid)
    assert "ex:age" in src and "integer" in src


def test_write_guards_conflict_duplicate_prefix_notfound(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """Stale revision → 409; existing IRI → DUPLICATE_ENTITY; bad prefix → 422."""
    oid, meta = _upload(client)
    dup = {
        "name": "Dog",
        "prefix": "ex",
        "parents": [],
        "baseRevision": meta["revision"],
    }
    r = client.post(f"/api/ontologies/{oid}/classes", json=dup)
    assert r.status_code == 409
    assert r.json()["code"] == "DUPLICATE_ENTITY"

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "X", "prefix": "nope", "parents": [], "baseRevision": meta["revision"]},
    )
    assert r.status_code == 422
    assert "ex" in (r.json()["hint"] or "")

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "X", "prefix": "ex", "parents": [], "baseRevision": 99},
    )
    assert r.status_code == 409
    assert r.json()["code"] == "EDIT_CONFLICT"

    r = client.post(
        "/api/ontologies/00000000-0000-0000-0000-000000000000/classes",
        json={"name": "X", "prefix": "ex", "parents": [], "baseRevision": 0},
    )
    assert r.status_code == 404


def test_invalid_iri_refs_are_422_and_file_unchanged(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """Scheme-less/spacey IRIs into parents/domains/ranges are 422, not 500.

    Every gate fires before the first mutation, so the stored file (and its
    revision — the lock token) is untouched after each refusal.
    """
    oid, meta = _upload(client)
    before = _source(client, oid)

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "X",
            "prefix": "ex",
            "parents": ["not an iri"],
            "baseRevision": meta["revision"],
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
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 422

    r = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={"parents": ["http://exa mple.org/A"], "baseRevision": meta["revision"]},
    )
    assert r.status_code == 422
    assert "absolute IRI" in (r.json()["hint"] or "")

    # Refused everywhere: file untouched, revision still valid for the next write.
    assert _source(client, oid) == before
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    assert meta2["revision"] == meta["revision"]
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Y", "prefix": "ex", "parents": [], "baseRevision": meta2["revision"]},
    )
    assert r.status_code == 200


def test_update_entity_label_comment_parents(client: TestClient, autosave_debounce_50ms) -> None:
    """PUT /entities rewrites label/comment/parents but keeps restrictions."""
    oid, meta = _upload(client)
    r = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={
            "label": {"value": "狗", "lang": "zh"},
            "comment": "Good dog.",
            "parents": [THING],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    ent = client.get(f"/api/ontologies/{oid}/entities/{DOG}").json()["data"]
    assert ent["label"] == {"zh": "狗"}
    assert ent["comment"] == "Good dog."
    assert [p["eid"] for p in ent["parents"]] == [THING]
    _wait_landed(client, oid)
    # The owl:Restriction blank-node axiom survives the reparent.
    assert "Restriction" in _source(client, oid)


def test_update_entity_clears_with_empty_and_404s_on_unknown(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """parents: [] clears named parents; unknown eid is 404."""
    oid, meta = _upload(client)
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.put(
        f"/api/ontologies/{oid}/entities/{ANIMAL}",
        json={"parents": [], "baseRevision": meta2["revision"]},
    )
    assert r.status_code == 200
    ent = client.get(f"/api/ontologies/{oid}/entities/{ANIMAL}").json()["data"]
    assert ent["parents"] == []

    meta3 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.put(
        f"/api/ontologies/{oid}/entities/{'http://example.org/Ghost'}",
        json={"comment": "x", "baseRevision": meta3["revision"]},
    )
    assert r.status_code == 404


def test_delete_entity_prunes_reverse_references(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """DELETE removes the entity and (prune) every edge pointing at it."""
    oid, meta = _upload(client)
    r = client.delete(
        f"/api/ontologies/{oid}/entities/{ANIMAL}?baseRevision={meta['revision']}&prune=true"
    )
    assert r.status_code == 200
    ov = _overview(client, oid)
    assert all(n["id"] != ANIMAL for n in ov["nodes"])
    _wait_landed(client, oid)
    src = _source(client, oid)
    assert "ex:Animal" not in src


def test_delete_keeps_dangling_references_without_prune(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """prune=false leaves reverse triples in the file."""
    oid, meta = _upload(client)
    r = client.delete(
        f"/api/ontologies/{oid}/entities/{ANIMAL}?baseRevision={meta['revision']}&prune=false"
    )
    assert r.status_code == 200
    _wait_landed(client, oid)
    src = _source(client, oid)
    # Dog's subClassOf → Animal survives as a dangling reference.
    assert "ex:Animal" in src


def test_entity_write_refreshes_disk_ir_cache(
    client: TestClient, autosave_debounce_50ms, monkeypatch
) -> None:
    """After a class create, a dropped memory cache serves without re-parse.

    The autosave's write_ir_cache moved the pkl onto the new file hash, so
    the cold path hits the pkl instead of the parser.
    """
    import ontoworkbench.server.routers.browse as browse_mod

    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={
            "name": "Cat",
            "prefix": "ex",
            "parents": [ANIMAL],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    _wait_landed(client, oid)

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


def test_edit_parses_file_once_and_keeps_parse_ms(
    client: TestClient, autosave_debounce_50ms, monkeypatch
) -> None:
    """An edit parses the file exactly once.

    cache.load_store is the only parse; neither the IR patch nor the
    autosave re-parses. stats_json keeps the old parse_ms and gains
    build_ms when the autosave lands.
    """
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
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200, r.text
    assert calls == [1]  # load_store only; patch + autosave never re-parse

    _wait_landed(client, oid)
    after = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    assert after["parseMs"] == meta["parseMs"]  # kept from the original parse
    with sessionmaker_or_fail()() as session:
        row = session.get(Ontology, UUID(oid))
        assert row is not None
        assert row.stats_json["build_ms"] is not None  # written by the autosave
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


def test_create_class_in_default_namespace(client: TestClient, autosave_debounce_50ms) -> None:
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
        json={"name": "Cat", "prefix": "", "parents": [], "baseRevision": meta["revision"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["entity"] == {
        "eid": "http://example.org/Cat",
        "curie": ":Cat",
        "type": "Class",
    }

    # The dumped file keeps the default prefix bound and re-parses cold
    _wait_landed(client, oid)
    client.app.state.cache.drop(oid)
    ov = _overview(client, oid)
    assert any(n["id"] == "http://example.org/Cat" and n["curie"] == ":Cat" for n in ov["nodes"])
    assert ":Cat a owl:Class" in _source(client, oid)


def test_edit_rdfxml_default_namespace_round_trips(
    client: TestClient, autosave_debounce_50ms
) -> None:
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
        json={"comment": "root", "baseRevision": meta["revision"]},
    )
    assert r.status_code == 200, r.text
    _wait_landed(client, oid)

    src = _source(client, oid)
    assert 'xmlns="http://example.org/"' in src  # default namespace survives
    # The dumped file re-parses: a second edit on the refreshed revision works.
    meta2 = client.get(f"/api/ontologies/{oid}/meta").json()["data"]
    r = client.put(
        f"/api/ontologies/{oid}/entities/{ANIMAL}",
        json={"comment": "child", "baseRevision": meta2["revision"]},
    )
    assert r.status_code == 200, r.text
    _wait_landed(client, oid)
    assert "child" in _source(client, oid)


JSONLD_CONTEXT = b"""{
  "@context": {
    "ex": "http://example.org/",
    "owl": "http://www.w3.org/2002/07/owl#"
  },
  "@id": "ex:Thing",
  "@type": "owl:Class"
}"""


def test_edit_jsonld_round_trips(client: TestClient, autosave_debounce_50ms) -> None:
    """Creating a class in a jsonld ontology survives the dump + re-parse."""
    r = client.post(
        "/api/ontologies",
        files={"file": ("mini.jsonld", io.BytesIO(JSONLD_CONTEXT), "application/ld+json")},
    )
    assert r.status_code == 201
    oid, meta = r.json()["data"]["id"], r.json()["data"]

    r = client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": "Cat", "prefix": "ex", "baseRevision": meta["revision"]},
    )
    assert r.status_code == 200, r.text
    assert r.json()["data"]["entity"]["curie"] == "ex:Cat"

    # Force the cold path: the dumped file must re-parse and serve the edit.
    _wait_landed(client, oid)
    client.app.state.cache.drop(oid)
    ov = _overview(client, oid)
    assert any(n["id"] == "http://example.org/Cat" for n in ov["nodes"])
