"""LRU caches keyed by ontology id: built Indexes and editable Stores."""

from __future__ import annotations

import threading
from collections import OrderedDict, defaultdict
from collections.abc import Callable
from pathlib import Path

from pyoxigraph import Store

from ontoworkbench.core.indexes import Indexes
from ontoworkbench.core.parsing import parse_store
from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.db.models import Ontology
from ontoworkbench.observability.metrics import (
    ow_cached_ontologies,
    ow_cached_stores,
    ow_parse_seconds,
)

CACHE_SIZE = 10
STORE_CACHE_SIZE = 2


def load_store(row: Ontology) -> tuple[Store, PrefixMap]:
    """Parse the stored file into a Store for the pool (parse timed per format).

    The canonical store_for loader: entities' write endpoints and lint's
    read-only runs both feed the pool through it.
    """
    data = Path(row.storage_path).read_bytes()
    with ow_parse_seconds.labels(row.format).time():
        return parse_store(data, row.format)


class OntologyCache:
    """Holds up to CACHE_SIZE parsed indexes; invalidates on hash/mtime change.

    A second, smaller pool holds the editable pyoxigraph Stores behind the
    write endpoints (STORE_CACHE_SIZE, LRU): a repeat edit reuses the
    already-parsed Store instead of re-reading the file. Entries validate
    by file_hash; callers mutate the cached instance in place and report
    the outcome via refresh_store (write landed) or drop_store (write
    failed / file replaced), so the pool never serves a Store that
    diverged from the file on disk.
    """

    def __init__(self, max_size: int = CACHE_SIZE, store_max_size: int = STORE_CACHE_SIZE) -> None:
        """Start empty with the given capacities."""
        self._max_size = max_size
        self._entries: OrderedDict[str, tuple[str, float, Indexes]] = OrderedDict()
        self._store_max_size = store_max_size
        self._stores: OrderedDict[str, tuple[str, Store, PrefixMap]] = OrderedDict()
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)

    def indexes_for(
        self,
        ontology: Ontology,
        loader: Callable[[Ontology], Indexes],
    ) -> Indexes:
        """Return cached indexes, rebuilding when the stored file changed.

        Concurrent misses for the same ontology collapse into one loader
        run: the first request through the per-oid lock builds, the rest
        double-check the cache inside the lock and share the result.
        """
        key = str(ontology.id)
        try:
            mtime = Path(ontology.storage_path).stat().st_mtime
        except OSError:
            mtime = -1.0
        cached = self._entries.get(key)
        if cached and cached[0] == ontology.file_hash and cached[1] == mtime:
            self._entries.move_to_end(key)
            return cached[2]
        with self._locks[key]:
            cached = self._entries.get(key)
            if cached and cached[0] == ontology.file_hash and cached[1] == mtime:
                self._entries.move_to_end(key)
                return cached[2]
            indexes = loader(ontology)
            self._entries[key] = (ontology.file_hash, mtime, indexes)
            while len(self._entries) > self._max_size:
                self._entries.popitem(last=False)
            ow_cached_ontologies.set(len(self._entries))
            return indexes

    def store_for(
        self,
        ontology: Ontology,
        loader: Callable[[Ontology], tuple[Store, PrefixMap]],
    ) -> tuple[Store, PrefixMap]:
        """Return the editable Store for this row, parsing only on a miss.

        Same single-flight shape as indexes_for: concurrent misses for one
        ontology collapse into one loader run behind the per-oid lock, and
        the entry validates by file_hash. The Store handed out IS the
        cached instance — callers mutate it in place, then refresh_store
        it or (on failure) drop_store it.
        """
        key = str(ontology.id)
        with self._locks[key]:
            cached = self._stores.get(key)
            if cached and cached[0] == ontology.file_hash:
                self._stores.move_to_end(key)
                return cached[1], cached[2]
            store, prefixes = loader(ontology)
            self._stores[key] = (ontology.file_hash, store, prefixes)
            self._stores.move_to_end(key)
            while len(self._stores) > self._store_max_size:
                self._stores.popitem(last=False)
            ow_cached_stores.set(len(self._stores))
            return store, prefixes

    def refresh_store(self, ontology: Ontology, store: Store, prefixes: PrefixMap) -> None:
        """Re-key the entry under the row's new file_hash after a landed edit."""
        key = str(ontology.id)
        with self._locks[key]:
            self._stores[key] = (ontology.file_hash, store, prefixes)
            self._stores.move_to_end(key)
            while len(self._stores) > self._store_max_size:
                self._stores.popitem(last=False)
            ow_cached_stores.set(len(self._stores))

    def drop_store(self, ontology_id: str) -> bool:
        """Evict one editable Store (persist failure, source replace); True when live."""
        with self._locks[ontology_id]:
            lived = self._stores.pop(ontology_id, None) is not None
            if lived:
                # drop() routes here too, so its evictions stay gauged.
                ow_cached_stores.set(len(self._stores))
            return lived

    def drop(self, ontology_id: str) -> bool:
        """Evict one ontology's caches (called on delete); True when any lived."""
        store_evicted = self.drop_store(ontology_id)
        index_evicted = self._entries.pop(ontology_id, None) is not None
        evicted = store_evicted or index_evicted
        if evicted:
            ow_cached_ontologies.set(len(self._entries))
        return evicted
