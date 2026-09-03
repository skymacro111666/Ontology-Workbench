"""ir_cache primitives: roundtrip, triple invalidation, atomic write, tolerance."""

from __future__ import annotations

import os
import pickle
from pathlib import Path

import pytest

from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.ir_cache import (
    ir_cache_path,
    read_ir_cache,
    write_ir_cache,
)
from ontoworkbench.core.parsing import parse_graph

TTL = b"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; <http://www.w3.org/2000/01/rdf-schema#subClassOf> ex:Thing .
"""
HASH = "a" * 64


def _ir() -> object:
    return build_ir(parse_graph(TTL, "turtle"))


def test_roundtrip_hit(tmp_path: Path) -> None:
    """Write then read back an equal IRBundle under the matching hash."""
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)
    ir = _ir()

    assert write_ir_cache(store, ir, HASH) is True
    result = read_ir_cache(store, HASH)

    assert result.outcome == "hit"
    assert result.ir == ir


def test_missing_file_is_miss(tmp_path: Path) -> None:
    """No cache file at all -> miss (never an error)."""
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)

    assert read_ir_cache(store, HASH) == (None, "miss")


def test_hash_mismatch_is_miss(tmp_path: Path) -> None:
    """A stale hash (the ontology changed) must not serve old IR."""
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)
    write_ir_cache(store, _ir(), HASH)

    assert read_ir_cache(store, "b" * 64).outcome == "miss"


def test_version_drift_is_miss(tmp_path: Path) -> None:
    """A payload from a different IR_SCHEMA_VERSION misses, not corrupts."""
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)
    ir_cache_path(store).write_bytes(pickle.dumps({"v": 999, "file_hash": HASH, "ir": _ir()}))

    assert read_ir_cache(store, HASH).outcome == "miss"


def test_corrupt_file_is_corrupt_never_raises(tmp_path: Path) -> None:
    """Garbage bytes surface as corrupt; the caller falls back to re-parse."""
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)
    ir_cache_path(store).write_bytes(b"\x80\x04 not-a-pickle")

    assert read_ir_cache(store, HASH) == (None, "corrupt")


def test_write_leaves_no_tmp(tmp_path: Path) -> None:
    """The swap-in completes: no index.pkl.tmp sibling survives."""
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)

    write_ir_cache(store, _ir(), HASH)

    assert ir_cache_path(store).is_file()
    assert not (tmp_path / "index.pkl.tmp").exists()


def test_write_failure_returns_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An os.replace failure logs and returns False — it must not raise."""

    def boom(src: object, dst: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    store = tmp_path / "mini.ttl"
    store.write_bytes(TTL)

    assert write_ir_cache(store, _ir(), HASH) is False


def test_write_never_clobbers_a_source_named_like_the_cache(tmp_path: Path) -> None:
    """An ontology file named index.pkl (or index.pkl.tmp) must survive.

    The cache path / tmp path can coincide with the source file itself;
    writing would silently destroy the uploaded ontology. Both calls
    refuse, and not one byte of either file changes.
    """
    src_cache_named = tmp_path / "index.pkl"
    src_tmp_named = tmp_path / "index.pkl.tmp"
    src_cache_named.write_bytes(TTL)
    src_tmp_named.write_bytes(TTL)

    assert write_ir_cache(src_cache_named, _ir(), HASH) is False
    assert write_ir_cache(src_tmp_named, _ir(), HASH) is False

    assert src_cache_named.read_bytes() == TTL
    assert src_tmp_named.read_bytes() == TTL
