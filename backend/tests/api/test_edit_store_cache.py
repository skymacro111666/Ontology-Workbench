"""The editable-Store pool: repeat edits parse zero times (plan Task 10).

Every edit pulls the ontology's Store from an LRU pool inside OntologyCache,
keyed by (ontology id, file_hash): the first edit parses the file, later
edits reuse the mutated instance until something else rewrites the file
(PUT /source, a failed persist, LRU pressure).
"""

import io
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ontoworkbench.server.cache as cache_mod

MINI = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal .
"""

MINI2 = MINI + b"ex:Wolf a owl:Class ; rdfs:subClassOf ex:Animal .\n"

EX = "http://example.org/"
DOG = f"{EX}Dog"


def _upload(client: TestClient, data: bytes = MINI, name: str = "mini.ttl") -> tuple[str, Any]:
    r = client.post("/api/ontologies", files={"file": (name, io.BytesIO(data), "text/turtle")})
    assert r.status_code == 201
    return r.json()["data"]["id"], r.json()["data"]


def _meta(client: TestClient, oid: str) -> dict[str, Any]:
    return client.get(f"/api/ontologies/{oid}/meta").json()["data"]


def _source(client: TestClient, oid: str) -> str:
    return client.get(f"/api/ontologies/{oid}/source").json()["data"]["content"]


def _create_class(client: TestClient, oid: str, name: str, base: str):  # noqa: ANN001
    return client.post(
        f"/api/ontologies/{oid}/classes",
        json={"name": name, "prefix": "ex", "parents": [], "baseFileHash": base},
    )


def _parse_spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count parses on the edit path (cache.load_store's parse_store)."""
    calls: list[int] = []
    real = cache_mod.parse_store

    def spy(data: bytes, fmt: str) -> object:
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(cache_mod, "parse_store", spy)
    return calls


def test_second_edit_skips_parse(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """First edit parses once; the second reuses the pooled Store."""
    oid, meta = _upload(client)
    calls = _parse_spy(monkeypatch)
    r1 = _create_class(client, oid, "Cat", meta["fileHash"])
    assert r1.status_code == 200
    meta2 = _meta(client, oid)
    r2 = _create_class(client, oid, "Dog2", meta2["fileHash"])
    assert r2.status_code == 200
    assert calls == [1]  # first edit loaded; second reused the cached store
    assert "ex:Dog2" in _source(client, oid)


def test_external_write_invalidates(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """PUT /source changes file_hash → the next edit re-parses (cache miss)."""
    oid, meta = _upload(client)
    calls = _parse_spy(monkeypatch)
    r1 = _create_class(client, oid, "Cat", meta["fileHash"])
    assert r1.status_code == 200
    assert len(calls) == 1  # edit 1 warmed the pool

    meta2 = _meta(client, oid)
    r = client.put(
        f"/api/ontologies/{oid}/source",
        json={"content": MINI2.decode(), "baseFileHash": meta2["fileHash"]},
    )
    assert r.status_code == 200
    meta3 = _meta(client, oid)
    assert meta3["fileHash"] != meta2["fileHash"]

    r2 = _create_class(client, oid, "Dog2", meta3["fileHash"])
    assert r2.status_code == 200
    assert calls == [1, 1]  # the external write forced a re-parse


def test_failed_persist_evicts_dirty_store(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A persist failure never serves the half-edited Store again.

    The failed edit's mutations live only in the pooled Store while the
    file never changed; without eviction the retry would silently land
    them next to its own.
    """
    oid, meta = _upload(client)
    calls = _parse_spy(monkeypatch)

    real_save = client.app.state.store.save
    failed = {"once": False}

    def flaky_save(*args: object, **kwargs: object) -> object:
        if not failed["once"]:
            failed["once"] = True
            raise OSError("disk full")
        return real_save(*args, **kwargs)  # type: ignore[misc]

    monkeypatch.setattr(client.app.state.store, "save", flaky_save)
    with pytest.raises(OSError, match="disk full"):
        _create_class(client, oid, "Cat", meta["fileHash"])

    # File untouched by the failure: the lock token survives.
    meta2 = _meta(client, oid)
    assert meta2["fileHash"] == meta["fileHash"]

    r2 = _create_class(client, oid, "Dog2", meta2["fileHash"])
    assert r2.status_code == 200
    src = _source(client, oid)
    assert "ex:Dog2" in src
    assert "ex:Cat" not in src  # the failed edit never leaked into the file
    assert calls == [1, 1]  # the retry re-parsed: the dirty entry was evicted


def test_store_pool_lru_cap_is_two(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """A third ontology's edit evicts the least-recently-edited Store."""
    calls = _parse_spy(monkeypatch)
    oids = []
    for i in range(3):
        oid, meta = _upload(client, name=f"mini{i}.ttl")
        oids.append(oid)
        r = _create_class(client, oid, f"C{i}", meta["fileHash"])
        assert r.status_code == 200
    assert len(calls) == 3  # one parse per ontology: entries key by id, not hash
    assert "ex:C0" not in _source(client, oids[1])  # same bytes, separate stores

    # The pool now holds mini1+mini2; editing mini0 again must re-parse.
    meta0 = _meta(client, oids[0])
    r = _create_class(client, oids[0], "Again", meta0["fileHash"])
    assert r.status_code == 200
    assert len(calls) == 4


def _store_gauge(client: TestClient) -> float:
    """ow_cached_stores off /metrics (Gauge: literal name, no _total suffix)."""
    for line in client.get("/metrics").text.splitlines():
        if line.startswith("ow_cached_stores "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError("ow_cached_stores missing from /metrics")


def test_store_pool_gauge_tracks_size(client: TestClient) -> None:
    """ow_cached_stores mirrors the pool across a warm-up edit and a drop.

    The Gauge is process-global while each test gets a fresh cache, so the
    pre-mutation reading may be stale from an earlier test's app; from this
    app's first pool mutation on, the gauge reflects its own pool exactly
    (assertions are therefore absolute, not deltas).
    """
    oid, meta = _upload(client)
    r = _create_class(client, oid, "Cat", meta["fileHash"])
    assert r.status_code == 200
    assert _store_gauge(client) == 1.0  # store_for warmed the pool

    # A repeat edit reuses (moves) the entry — still exactly one Store.
    h2 = _meta(client, oid)["fileHash"]
    r = _create_class(client, oid, "Dog2", h2)
    assert r.status_code == 200
    assert _store_gauge(client) == 1.0

    client.app.state.cache.drop(oid)  # routes through drop_store
    assert _store_gauge(client) == 0.0


def test_rejected_entity_update_never_lands_via_next_edit(client: TestClient) -> None:
    """C1 repro: a 422'd comment must not ride along with the next legal edit.

    update_entity applies label/comment before parents/domains/ranges
    validate; the 422 escapes _persist's guard, so without checkout-level
    eviction the pooled Store keeps the refused comment and the next
    successful write persists it.
    """
    oid, meta = _upload(client)
    r = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={
            "comment": "entity-leak-marker",
            "parents": ["not an iri"],  # 422 after the comment already applied
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 422

    h2 = _meta(client, oid)["fileHash"]
    r2 = client.put(
        f"/api/ontologies/{oid}/entities/{DOG}",
        json={"parents": [f"{EX}Thing"], "baseFileHash": h2},  # legal, leaves comment alone
    )
    assert r2.status_code == 200
    src = _source(client, oid)
    assert "entity-leak-marker" not in src  # the refused edit never landed
    assert "ex:Dog" in src and "subClassOf ex:Thing" in src  # positive control


def test_rejected_instance_update_never_lands_via_next_edit(client: TestClient) -> None:
    """C1 repro (instances): same shape — 422'd comment vs. later classes.

    update_instance applies the comment before the classes/assertions
    branches validate.
    """
    oid, meta = _upload(client)
    r = client.post(
        f"/api/ontologies/{oid}/instances",
        json={
            "name": "ThreeBody",
            "prefix": "ex",
            "classes": [f"{EX}Animal"],
            "baseFileHash": meta["fileHash"],
        },
    )
    assert r.status_code == 200
    h2 = _meta(client, oid)["fileHash"]

    r = client.put(
        f"/api/ontologies/{oid}/instances/{EX}ThreeBody",
        json={
            "comment": "instance-leak-marker",
            "classes": [f"{EX}Nope"],  # undeclared → 422 after the comment applied
            "baseFileHash": h2,
        },
    )
    assert r.status_code == 422

    h3 = _meta(client, oid)["fileHash"]
    r2 = client.put(
        f"/api/ontologies/{oid}/instances/{EX}ThreeBody",
        json={"classes": [f"{EX}Thing"], "baseFileHash": h3},  # legal, leaves comment alone
    )
    assert r2.status_code == 200
    src = _source(client, oid)
    assert "instance-leak-marker" not in src
    assert "ex:ThreeBody" in src and "ex:Thing" in src  # positive control
