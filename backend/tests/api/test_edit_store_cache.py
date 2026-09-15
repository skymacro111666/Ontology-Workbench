"""The editable-Store pool: repeat edits parse zero times (plan Task 10).

Every edit pulls the ontology's Store from an LRU pool inside OntologyCache,
keyed by (ontology id, file_hash): the first edit parses the file, later
edits reuse the mutated instance until something else rewrites the file
(PUT /source, a failed checkout, LRU pressure). The autosave's
refresh_store re-keys the entry under the landed file's hash, so the pool
survives the debounced save without a re-parse.
"""

import io
import time
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
    r = client.post("/api/v1/ontologies", files={"file": (name, io.BytesIO(data), "text/turtle")})
    assert r.status_code == 201
    return r.json()["data"]["id"], r.json()["data"]


def _meta(client: TestClient, oid: str) -> dict[str, Any]:
    return client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]


def _source(client: TestClient, oid: str) -> str:
    return client.get(f"/api/v1/ontologies/{oid}/source").json()["data"]["content"]


def _create_class(client: TestClient, oid: str, name: str, base: int):  # noqa: ANN001
    return client.post(
        f"/api/v1/ontologies/{oid}/classes",
        json={"name": name, "prefix": "ex", "parents": [], "baseRevision": base},
    )


def _wait_landed(client: TestClient, oid: str, timeout: float = 2.0) -> None:
    """Block until the oid's autosave is idle again (file on disk, row fresh)."""
    manager = client.app.state.autosave
    deadline = time.monotonic() + timeout
    while manager.state(oid) != "idle":
        if time.monotonic() > deadline:
            raise AssertionError(f"autosave did not land within {timeout}s")
        time.sleep(0.02)


def _parse_spy(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count parses on the edit path (cache.load_store's parse_store)."""
    calls: list[int] = []
    real = cache_mod.parse_store

    def spy(data: bytes, fmt: str) -> object:
        calls.append(1)
        return real(data, fmt)

    monkeypatch.setattr(cache_mod, "parse_store", spy)
    return calls


def test_second_edit_skips_parse(
    client: TestClient, autosave_debounce_50ms, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First edit parses once; the second reuses the pooled Store."""
    oid, meta = _upload(client)
    calls = _parse_spy(monkeypatch)
    r1 = _create_class(client, oid, "Cat", meta["revision"])
    assert r1.status_code == 200
    _wait_landed(client, oid)  # autosave re-keys the pool under the new hash
    meta2 = _meta(client, oid)
    r2 = _create_class(client, oid, "Dog2", meta2["revision"])
    assert r2.status_code == 200
    assert calls == [1]  # first edit loaded; second reused the cached store
    _wait_landed(client, oid)
    assert "ex:Dog2" in _source(client, oid)


def test_external_write_invalidates(
    client: TestClient, autosave_debounce_50ms, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT /source changes file_hash → the next edit re-parses (cache miss)."""
    oid, meta = _upload(client)
    calls = _parse_spy(monkeypatch)
    r1 = _create_class(client, oid, "Cat", meta["revision"])
    assert r1.status_code == 200
    assert len(calls) == 1  # edit 1 warmed the pool
    _wait_landed(client, oid)  # land before the replace: no pending save races it

    meta2 = _meta(client, oid)
    r = client.put(
        f"/api/v1/ontologies/{oid}/source",
        json={"content": MINI2.decode(), "baseFileHash": meta2["fileHash"]},
    )
    assert r.status_code == 200
    meta3 = _meta(client, oid)
    assert meta3["fileHash"] != meta2["fileHash"]

    r2 = _create_class(client, oid, "Dog2", meta3["revision"])
    assert r2.status_code == 200
    assert calls == [1, 1]  # the external write forced a re-parse
    _wait_landed(client, oid)
    assert "ex:Dog2" in _source(client, oid)


def test_autosave_disk_failure_retries_and_lands(
    client: TestClient, autosave_debounce_50ms, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing disk write no longer fails the edit: autosave retries it.

    The Y-axis commit already landed (revision bumped, IR patched), so a
    transient OSError in the saver must not lose the edit — the retry
    (retry_base=0.05 here) saves the same Store a moment later.
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
    r = _create_class(client, oid, "Cat", meta["revision"])
    assert r.status_code == 200  # returns fast despite the (later) disk hiccup
    assert r.json()["data"]["meta"]["revision"] == 1

    _wait_landed(client, oid)  # first attempt failed; the retry lands
    assert "ex:Cat" in _source(client, oid)
    assert _meta(client, oid)["saveState"] == "idle"
    assert calls == [1]  # the retry re-serializes; it never re-parses


def test_store_pool_lru_cap_is_two(
    client: TestClient, autosave_debounce_50ms, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third ontology's edit evicts the least-recently-edited Store."""
    calls = _parse_spy(monkeypatch)
    oids = []
    for i in range(3):
        oid, meta = _upload(client, name=f"mini{i}.ttl")
        oids.append(oid)
        r = _create_class(client, oid, f"C{i}", meta["revision"])
        assert r.status_code == 200
        _wait_landed(client, oid)  # savers re-key entries: no background churn
    assert len(calls) == 3  # one parse per ontology: entries key by id, not hash
    assert "ex:C0" not in _source(client, oids[1])  # same bytes, separate stores

    # The pool now holds mini1+mini2; editing mini0 again must re-parse.
    meta0 = _meta(client, oids[0])
    r = _create_class(client, oids[0], "Again", meta0["revision"])
    assert r.status_code == 200
    assert len(calls) == 4


def _store_gauge(client: TestClient) -> float:
    """ow_cached_stores off /metrics (Gauge: literal name, no _total suffix)."""
    for line in client.get("/metrics").text.splitlines():
        if line.startswith("ow_cached_stores "):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError("ow_cached_stores missing from /metrics")


def test_store_pool_gauge_tracks_size(client: TestClient, autosave_debounce_50ms) -> None:
    """ow_cached_stores mirrors the pool across a warm-up edit and a drop.

    The Gauge is process-global while each test gets a fresh cache, so the
    pre-mutation reading may be stale from an earlier test's app; from this
    app's first pool mutation on, the gauge reflects its own pool exactly
    (assertions are therefore absolute, not deltas).
    """
    oid, meta = _upload(client)
    r = _create_class(client, oid, "Cat", meta["revision"])
    assert r.status_code == 200
    assert _store_gauge(client) == 1.0  # store_for warmed the pool

    # A repeat edit reuses (moves) the entry — still exactly one Store.
    _wait_landed(client, oid)  # the saver's refresh_store re-keys, never adds
    rev = _meta(client, oid)["revision"]
    r = _create_class(client, oid, "Dog2", rev)
    assert r.status_code == 200
    assert _store_gauge(client) == 1.0
    _wait_landed(client, oid)  # no background save may re-add after the drop

    client.app.state.cache.drop(oid)  # routes through drop_store
    assert _store_gauge(client) == 0.0


def test_rejected_entity_update_never_lands_via_next_edit(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """C1 repro: a 422'd comment must not ride along with the next legal edit.

    update_entity applies label/comment before parents/domains/ranges
    validate; the 422 escapes before any commit, so without checkout-level
    eviction the pooled Store keeps the refused comment and the next
    successful write persists it.
    """
    oid, meta = _upload(client)
    r = client.put(
        f"/api/v1/ontologies/{oid}/entities/{DOG}",
        json={
            "comment": "entity-leak-marker",
            "parents": ["not an iri"],  # 422 after the comment already applied
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 422

    rev = _meta(client, oid)["revision"]  # refusals bump nothing
    r2 = client.put(
        f"/api/v1/ontologies/{oid}/entities/{DOG}",
        json={"parents": [f"{EX}Thing"], "baseRevision": rev},  # legal, leaves comment alone
    )
    assert r2.status_code == 200
    _wait_landed(client, oid)
    src = _source(client, oid)
    assert "entity-leak-marker" not in src  # the refused edit never landed
    assert "ex:Dog" in src and "subClassOf ex:Thing" in src  # positive control


def test_rejected_update_after_pending_edit_neither_leaks_nor_loses(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """A 422 between a pending edit and its save must neither leak nor lose.

    The pending saver serializes the very Store object the refused edit
    partly mutated under the old ordering, and drop_store makes the next
    edit re-parse the stale disk file — so validation must run before
    the first mutation (validate-then-mutate) and the clean Store stays
    pooled for the next edit.
    """
    oid, meta = _upload(client)
    r1 = _create_class(client, oid, "Cat", meta["revision"])  # pending, un-landed
    assert r1.status_code == 200
    r = client.put(
        f"/api/v1/ontologies/{oid}/entities/{DOG}",
        json={
            "comment": "leak-marker",
            "parents": ["not an iri"],  # 422 while the Cat save is still pending
            "baseRevision": _meta(client, oid)["revision"],
        },
    )
    assert r.status_code == 422

    rev = _meta(client, oid)["revision"]  # refusals bump nothing
    r2 = _create_class(client, oid, "Dog2", rev)
    assert r2.status_code == 200
    _wait_landed(client, oid)
    src = _source(client, oid)
    assert "leak-marker" not in src  # refused fields never land
    assert "ex:Cat" in src and "ex:Dog2" in src  # both committed edits survive


def test_rejected_instance_update_never_lands_via_next_edit(
    client: TestClient, autosave_debounce_50ms
) -> None:
    """C1 repro (instances): same shape — 422'd comment vs. later classes.

    instances.py rides the same incremental pipeline (baseRevision lock +
    debounced autosave) as entities.py now.
    """
    oid, meta = _upload(client)
    r = client.post(
        f"/api/v1/ontologies/{oid}/instances",
        json={
            "name": "ThreeBody",
            "prefix": "ex",
            "classes": [f"{EX}Animal"],
            "baseRevision": meta["revision"],
        },
    )
    assert r.status_code == 200
    rev = _meta(client, oid)["revision"]

    r = client.put(
        f"/api/v1/ontologies/{oid}/instances/{EX}ThreeBody",
        json={
            "comment": "instance-leak-marker",
            "classes": [f"{EX}Nope"],  # undeclared → 422 after the comment applied
            "baseRevision": rev,
        },
    )
    assert r.status_code == 422

    rev2 = _meta(client, oid)["revision"]  # refusals bump nothing
    r2 = client.put(
        f"/api/v1/ontologies/{oid}/instances/{EX}ThreeBody",
        json={"classes": [f"{EX}Thing"], "baseRevision": rev2},  # legal, leaves comment alone
    )
    assert r2.status_code == 200
    _wait_landed(client, oid)
    src = _source(client, oid)
    assert "instance-leak-marker" not in src
    assert "ex:ThreeBody" in src and "ex:Thing" in src  # positive control
