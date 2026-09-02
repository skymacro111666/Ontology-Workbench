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


def test_sample_path_serves_every_bundled_ttl(tmp_path) -> None:
    """The catalog is the samples dir itself — no name registration to forget.

    Regression (sample since retired): one once shipped but stayed
    unloadable (NOT_FOUND) because a hardcoded allowlist never learned it.
    """
    store = LocalUserDirStore(tmp_path)
    samples_dir = store._samples
    bundled = {p.stem for p in samples_dir.glob("*.ttl")}
    assert bundled  # the shipped catalog, ground truth
    for name in bundled:
        assert store.sample_path(name).exists()


@pytest.mark.parametrize("bad", ["..", "../x", "a/b", ".hidden", "UPPER", "sp ace"])
def test_sample_path_rejects_non_catalog_names(tmp_path, bad: str) -> None:
    """Names outside the kebab-case catalog form are NOT_FOUND, not path games."""
    store = LocalUserDirStore(tmp_path)
    with pytest.raises(CoreError) as e:
        store.sample_path(bad)
    assert e.value.code == "NOT_FOUND"


def test_save_rejects_path_traversal(tmp_path) -> None:
    """Filenames with path separators cannot escape the ontology dir."""
    store = LocalUserDirStore(tmp_path)
    for bad in ("../escape.ttl", "a/b.ttl", "/abs.ttl"):
        with pytest.raises(CoreError) as exc:
            store.save(uuid4(), uuid4(), bad, b"x")
        assert exc.value.code == "VALIDATION_ERROR"


def test_save_overwrites_atomically(tmp_path) -> None:
    """Re-saving the same oid+filename replaces content and leaves no tmp file."""
    store = LocalUserDirStore(tmp_path)
    uid, oid = uuid4(), uuid4()
    first = store.save(uid, oid, "a.ttl", b"one")
    second = store.save(uid, oid, "a.ttl", b"twelve")
    assert first == second
    assert first.read_bytes() == b"twelve"
    assert [f.name for f in first.parent.iterdir()] == ["a.ttl"]
