"""OntologyCache concurrency: same-oid loads share one loader run."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ontoworkbench.server.cache import OntologyCache


class _Row:
    """Minimal Ontology stand-in: cache touches id/storage_path/file_hash."""

    def __init__(self, oid: str = "oid-1", file_hash: str = "h1") -> None:
        self.id = oid
        self.storage_path = str(Path("/nonexistent") / f"{oid}.ttl")
        self.file_hash = file_hash


def test_same_oid_concurrent_loads_run_loader_once() -> None:
    """Eight concurrent misses collapse into one slow loader run."""
    cache = OntologyCache(max_size=2)
    calls: list[int] = []

    def slow_loader(row: _Row) -> object:
        calls.append(1)
        time.sleep(0.2)  # hold the lock so laggards pile up behind it
        return object()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: cache.indexes_for(_Row(), slow_loader), range(8)))

    assert calls == [1]
    assert all(r is results[0] for r in results)


def test_second_call_hits_cache_without_loader() -> None:
    """A following call is served from the entry the first one stored."""
    cache = OntologyCache(max_size=2)
    calls: list[int] = []

    def loader(row: _Row) -> object:
        calls.append(1)
        return object()

    first = cache.indexes_for(_Row(), loader)
    second = cache.indexes_for(_Row(), loader)

    assert calls == [1]
    assert second is first


def test_different_oids_do_not_serialize_each_other() -> None:
    """A slow load for oid-a never blocks a concurrent load for oid-b."""
    cache = OntologyCache(max_size=2)

    def slow_a(row: _Row) -> object:
        time.sleep(0.3)
        return "a"

    def quick_b(row: _Row) -> object:
        return "b"

    with ThreadPoolExecutor(max_workers=2) as pool:
        fa = pool.submit(cache.indexes_for, _Row("oid-a"), slow_a)
        time.sleep(0.05)  # ensure oid-a's lock is held first
        fb = pool.submit(cache.indexes_for, _Row("oid-b"), quick_b)
        assert fb.result(timeout=0.15) == "b"  # finished while a still held
        assert fa.result(timeout=1) == "a"
