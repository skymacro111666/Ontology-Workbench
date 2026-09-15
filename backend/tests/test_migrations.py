"""Migration chain must apply cleanly on a fresh database (the `ow serve` boot path)."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from ontoworkbench.cli import _migrate
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine


def test_upgrade_head_on_fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Startup runs `alembic upgrade head`; every revision must construct valid DDL."""
    db_url = f"sqlite:///{tmp_path}/ow.db"
    monkeypatch.setenv("OW_DB_URL", db_url)
    _migrate(db_url, tmp_path)

    engine = sa.create_engine(db_url)
    with engine.connect() as conn:
        version = conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = {
            row[0]
            for row in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
        ontology_cols = {row[1] for row in conn.execute(sa.text("PRAGMA table_info(ontologies)"))}
    engine.dispose()

    assert version == "0008"
    assert "ontology_layouts" in tables
    assert "lint_rules" in tables
    assert "validation_shapes" in tables
    assert "agent_tokens" in tables
    # 0005: provenance column lands with its upload default (no backfill).
    assert "source" in ontology_cols
    # 0006: edit-axis optimistic lock lands at 0 for every existing row.
    assert "revision" in ontology_cols


def test_migration_output_is_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`ow serve` boots logging first; alembic lines share the JSON envelope."""
    import json

    from ontoworkbench.observability.logging import setup_logging

    log_dir = tmp_path / "logs"
    db_url = f"sqlite:///{tmp_path}/ow.db"
    monkeypatch.setenv("OW_DB_URL", db_url)

    setup_logging(log_dir, "INFO")
    _migrate(db_url, tmp_path)

    lines = (log_dir / "ow-server.log").read_text(encoding="utf-8").splitlines()
    json_lines = [ln for ln in lines if ln.startswith("{")]
    assert json_lines, lines
    payloads = [json.loads(ln) for ln in json_lines]
    assert {p["event"] for p in payloads} == {"db.migrate"}
    assert any("0004" in p["message"] or "0005" in p["message"] for p in payloads)
    assert all(p["level"] == "info" and "timestamp" in p for p in payloads)


@pytest.fixture()
def db_session() -> Session:
    """In-memory SQLite session (same shape as tests/db/test_repositories.py)."""
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_validation_shapes_roundtrip(db_session):
    """Upsert overwrites the single shapes row per oid; get returns None when unsaved."""
    from uuid import uuid4

    from ontoworkbench.db.repositories import ValidationShapesRepository

    oid = uuid4()
    repo = ValidationShapesRepository(db_session)
    assert repo.get(oid) is None
    repo.upsert(oid, "@prefix sh: <http://www.w3.org/ns/shacl#> .\n")
    row = repo.get(oid)
    assert row is not None and row.source.startswith("@prefix sh:")
    repo.upsert(oid, "[] a sh:NodeShape .")
    assert repo.get(oid).source == "[] a sh:NodeShape ."
