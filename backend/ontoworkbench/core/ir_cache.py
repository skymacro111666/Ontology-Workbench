"""Pickled IR cache beside the stored ontology file (spec 2026-09-03 §2).

Restarts skip the parse + IR-build pass by loading the persisted IRBundle.
Indexes are deliberately NOT persisted: they rebuild in <1s and embed
truncation policy that must not be frozen on disk.
"""

from __future__ import annotations

import os
import pickle
import time
from pathlib import Path
from typing import Literal, NamedTuple

import structlog

from ontoworkbench.core.ir import IRBundle

# v2: pyoxigraph 迁移 — IR 改由 build_ir_store 组装(curie/prefix 口径从 rdflib
# 内置命名表换成 PrefixMap),语义等价但产物不必逐字节同;旧 v1 pkl 因版本
# 不匹配自动按 miss 处理、下次导入/浏览重建。
IR_SCHEMA_VERSION = 2  # IRBundle 结构或 build_ir 语义变更时必须 bump
CACHE_FILENAME = "index.pkl"

_log = structlog.get_logger("ow.cache")

Outcome = Literal["hit", "miss", "corrupt"]


class IrCacheResult(NamedTuple):
    """Read outcome; `ir` is None unless outcome == "hit"."""

    ir: IRBundle | None
    outcome: Outcome


def ir_cache_path(storage_path: Path) -> Path:
    """The cache sits beside the ontology file, inside the oid dir.

    A sibling FILE (not a subdirectory): store.delete unlinks files only,
    so keeping it flat means deletion cleans the cache for free.
    """
    return storage_path.with_name(CACHE_FILENAME)


def read_ir_cache(storage_path: Path, file_hash: str) -> IrCacheResult:
    """Load cached IR on hash+version match; never raises.

    Missing file, hash mismatch, version drift and unexpected payload shape
    are expected staleness ("miss"); only a payload that fails to unpickle
    is "corrupt".
    """
    path = ir_cache_path(storage_path)
    if not path.is_file():
        return IrCacheResult(None, "miss")
    try:
        obj = pickle.loads(path.read_bytes())
        ir = obj.get("ir") if isinstance(obj, dict) else None
        if (
            isinstance(obj, dict)
            and obj.get("v") == IR_SCHEMA_VERSION
            and obj.get("file_hash") == file_hash
            and isinstance(ir, IRBundle)
        ):
            return IrCacheResult(ir, "hit")
        return IrCacheResult(None, "miss")
    except Exception:
        return IrCacheResult(None, "corrupt")


def write_ir_cache(storage_path: Path, ir: IRBundle, file_hash: str) -> bool:
    """Persist the IR atomically; any failure logs and returns False.

    Same tmp + os.replace discipline as LocalUserDirStore.save, so a crash
    midway never leaves a half-written cache a later read could trust.
    """
    path = ir_cache_path(storage_path)
    tmp = path.with_name(CACHE_FILENAME + ".tmp")
    if path == storage_path or tmp == storage_path:
        _log.warning("ir_cache.refuses_same_path", target=str(storage_path))
        return False
    started = time.perf_counter()
    try:
        payload = pickle.dumps({"v": IR_SCHEMA_VERSION, "file_hash": file_hash, "ir": ir})
        tmp.write_bytes(payload)
        os.replace(tmp, path)
    except Exception as exc:
        _log.warning(
            "ir_cache.write_failed",
            target=str(path),
            error_type=type(exc).__name__,
        )
        return False
    _log.info(
        "ir_cache.write",
        target=str(path),
        size_bytes=len(payload),
        write_ms=round((time.perf_counter() - started) * 1000, 1),
    )
    return True
