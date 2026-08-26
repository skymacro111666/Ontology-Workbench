"""Migration chain must apply cleanly on a fresh database (the `ow serve` boot path)."""

from pathlib import Path

import pytest
import sqlalchemy as sa

from ontoworkbench.cli import _migrate


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
    engine.dispose()

    assert version == "0003"
    assert "ontology_layouts" in tables
