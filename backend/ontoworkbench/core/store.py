"""File storage under {data_dir}/users/{uid}/ontologies/{oid}/."""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from ontoworkbench.core.errors import CoreError

_SAMPLE_NAMES = {"pizza", "wine", "foaf"}


class LocalUserDirStore:
    """Owns the on-disk layout of ontology files (spec §4.3)."""

    def __init__(self, data_dir: Path) -> None:
        """Anchor the store under {data_dir}/users and locate bundled samples."""
        self.root = data_dir / "users"
        self._samples = Path(__file__).parent.parent / "samples"

    def _dir(self, user_id: UUID, ontology_id: UUID) -> Path:
        return self.root / str(user_id) / "ontologies" / str(ontology_id)

    def save(self, user_id: UUID, ontology_id: UUID, filename: str, data: bytes) -> Path:
        """Write bytes under a fresh ontology dir; return final path."""
        d = self._dir(user_id, ontology_id)
        d.mkdir(parents=True, exist_ok=True)
        p = d / filename
        p.write_bytes(data)
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
        """Resolve a bundled sample ontology; unknown names are NOT_FOUND."""
        if name not in _SAMPLE_NAMES:
            raise CoreError("NOT_FOUND", f"Unknown sample '{name}'")
        p = self._samples / f"{name}.ttl"
        if not p.exists():
            raise CoreError("NOT_FOUND", f"Sample file missing for '{name}'")
        return p
