"""File storage under {data_dir}/users/{uid}/ontologies/{oid}/."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from uuid import UUID

from ontoworkbench.core.errors import CoreError

# Catalog names are kebab-case; anything else is NOT_FOUND before the
# filesystem ever sees it (the samples dir itself is the catalog — no
# registration list to drift out of sync with shipped files).
_SAMPLE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]*")


class LocalUserDirStore:
    """Owns the on-disk layout of ontology files (spec §4.3)."""

    def __init__(self, data_dir: Path) -> None:
        """Anchor the store under {data_dir}/users and locate bundled samples."""
        self.root = data_dir / "users"
        self._samples = Path(__file__).parent.parent / "samples"

    def _dir(self, user_id: UUID, ontology_id: UUID) -> Path:
        return self.root / str(user_id) / "ontologies" / str(ontology_id)

    def save(self, user_id: UUID, ontology_id: UUID, filename: str, data: bytes) -> Path:
        """Write bytes under a fresh ontology dir; return final path.

        The write lands on a sibling .tmp first and is swapped in with
        os.replace — same-directory rename, atomic on POSIX — so a crash
        midway never leaves a half-written ontology file.
        """
        if Path(filename).name != filename:
            raise CoreError(
                "VALIDATION_ERROR",
                f"Invalid filename '{filename!r}'",
                hint="Bare filename required",
            )
        d = self._dir(user_id, ontology_id)
        d.mkdir(parents=True, exist_ok=True)
        p = d / filename
        tmp = p.with_name(filename + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        return p

    def read(self, storage_path: Path) -> bytes:
        """Return the stored file's bytes."""
        return storage_path.read_bytes()

    def delete(self, user_id: UUID, ontology_id: UUID) -> None:
        """Remove the ontology dir and its contents (missing dir is a no-op)."""
        d = self._dir(user_id, ontology_id)
        if d.exists():
            for f in d.iterdir():
                f.unlink()
            d.rmdir()

    @staticmethod
    def file_hash(data: bytes) -> str:
        """sha256 hex for integrity/cache key."""
        return hashlib.sha256(data).hexdigest()

    def sample_path(self, name: str) -> Path:
        """Resolve a bundled sample ontology; unknown names are NOT_FOUND.

        Every .ttl shipped in the samples dir is servable — the catalog is
        the directory, so a new sample needs no code change to load.
        """
        if not _SAMPLE_NAME_RE.fullmatch(name):
            raise CoreError("NOT_FOUND", f"Unknown sample '{name}'")
        p = self._samples / f"{name}.ttl"
        if not p.exists():
            raise CoreError("NOT_FOUND", f"Sample file missing for '{name}'")
        return p
