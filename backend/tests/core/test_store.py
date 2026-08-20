"""LocalUserDirStore layout and lifecycle."""

from uuid import uuid4

import pytest

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.store import LocalUserDirStore


def test_save_read_delete_roundtrip(tmp_path) -> None:
    """Save writes under users/{uid}/ontologies/{oid}; read/delete manage it."""
    store = LocalUserDirStore(tmp_path)
    uid, oid = uuid4(), uuid4()
    p = store.save(uid, oid, "pizza.ttl", b"@prefix ... .")
    assert p == tmp_path / "users" / str(uid) / "ontologies" / str(oid) / "pizza.ttl"
    assert store.read(p) == b"@prefix ... ."
    store.delete(uid, oid)
    assert not p.parent.exists()


def test_file_hash_stable() -> None:
    """sha256 hex digest, stable across calls."""
    assert LocalUserDirStore.file_hash(b"x") == LocalUserDirStore.file_hash(b"x")
    assert len(LocalUserDirStore.file_hash(b"x")) == 64


def test_sample_path_unknown_raises_core_error(tmp_path) -> None:
    """Unknown sample names raise CoreError with code NOT_FOUND (no server import)."""
    store = LocalUserDirStore(tmp_path)
    with pytest.raises(CoreError) as e:
        store.sample_path("nope")
    assert e.value.code == "NOT_FOUND"


def test_save_rejects_path_traversal(tmp_path) -> None:
    """Filenames with path separators cannot escape the ontology dir."""
    store = LocalUserDirStore(tmp_path)
    for bad in ("../escape.ttl", "a/b.ttl", "/abs.ttl"):
        with pytest.raises(CoreError) as exc:
            store.save(uuid4(), uuid4(), bad, b"x")
        assert exc.value.code == "VALIDATION_ERROR"
