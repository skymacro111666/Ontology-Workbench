"""LRU cache of built Indexes keyed by ontology id, validated by hash+mtime."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

from ontoworkbench.core.indexes import Indexes
from ontoworkbench.db.models import Ontology
from ontoworkbench.observability.metrics import ow_cached_ontologies

CACHE_SIZE = 10


class OntologyCache:
    """Holds up to CACHE_SIZE parsed indexes; invalidates on hash/mtime change."""

    def __init__(self, max_size: int = CACHE_SIZE) -> None:
        """Start empty with the given capacity."""
        self._max_size = max_size
        self._entries: OrderedDict[str, tuple[str, float, Indexes]] = OrderedDict()

    def indexes_for(
        self,
        ontology: Ontology,
        loader: Callable[[Ontology], Indexes],
    ) -> Indexes:
        """Return cached indexes, rebuilding when the stored file changed."""
        key = str(ontology.id)
        try:
            mtime = Path(ontology.storage_path).stat().st_mtime
        except OSError:
            mtime = -1.0
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

    def drop(self, ontology_id: str) -> bool:
        """Evict one ontology (called on delete); True when a live entry existed."""
        evicted = self._entries.pop(ontology_id, None) is not None
        if evicted:
            ow_cached_ontologies.set(len(self._entries))
        return evicted
