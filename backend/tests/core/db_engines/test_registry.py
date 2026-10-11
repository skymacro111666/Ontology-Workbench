"""db_engines registry: dialects, urls, installed flags, type mapping."""

import pytest

from ontoworkbench.core.db_engines import (
    COMMON_TYPE_MAP,
    ENGINES,
    ConnValues,
    installed,
    map_type,
)


def _values() -> ConnValues:
    return ConnValues(host="db.internal", port=5432, database="app", username="u", password="p")


def test_registry_covers_three_engines() -> None:
    """postgres/mysql/sqlite register with labels and driver modules."""
    assert set(ENGINES) == {"postgres", "mysql", "sqlite"}
    assert ENGINES["postgres"].label == "PostgreSQL"
    assert ENGINES["mysql"].label == "MySQL"
    assert ENGINES["sqlite"].label == "SQLite"


def test_url_builders() -> None:
    """Each dialect renders its SQLAlchemy URL with driver pinning."""
    v = _values()
    assert ENGINES["postgres"].url(v) == "postgresql+psycopg://u:p@db.internal:5432/app"
    assert ENGINES["mysql"].url(v) == "mysql+pymysql://u:p@db.internal:5432/app"
    no_port = ConnValues(host="h", port=None, database="app", username="u", password=None)
    assert ENGINES["mysql"].url(no_port) == "mysql+pymysql://u@h:3306/app"
    sqlite = ConnValues(
        host=None, port=None, database="/data/shop.db", username=None, password=None
    )
    assert ENGINES["sqlite"].url(sqlite) == "sqlite:////data/shop.db"


def test_installed_flags() -> None:
    """Drivers are core dependencies now — every engine reports installed."""
    assert installed(ENGINES["sqlite"]) is True
    assert installed(ENGINES["postgres"]) is True
    assert installed(ENGINES["mysql"]) is True


def test_map_type_strips_lengths_and_falls_back() -> None:
    """VARCHAR(32) → string; unknown types fall back to xsd:string."""
    d = ENGINES["postgres"]
    assert map_type("VARCHAR(32)", d) == "xsd:string"
    assert map_type("BIGINT", d) == "xsd:integer"
    assert map_type("TIMESTAMPTZ", d) == "xsd:dateTime"
    assert map_type("WEIRDTYPE", d) == "xsd:string"


def test_map_type_dialect_overrides() -> None:
    """JSONB maps to string via the postgres override."""
    assert map_type("JSONB", ENGINES["postgres"]) == "xsd:string"


def test_common_map_contents() -> None:
    """The generic table covers the spec §4 mappings."""
    assert COMMON_TYPE_MAP["TEXT"] == "xsd:string"
    assert COMMON_TYPE_MAP["DECIMAL"] == "xsd:decimal"
    assert COMMON_TYPE_MAP["BOOL"] == "xsd:boolean"
    assert COMMON_TYPE_MAP["DOUBLE"] == "xsd:double"


def test_dialect_is_frozen_dataclass() -> None:
    """Dialect instances are immutable value objects."""
    d = ENGINES["sqlite"]
    with pytest.raises(Exception):  # noqa: B017 - frozen dataclass raises FrozenInstanceError
        d.db_type = "other"  # type: ignore[misc]


def test_drivers_are_core_dependencies() -> None:
    """Pyproject lists the drivers as core deps — no extras regression.

    Guards against a refactor quietly moving psycopg/pymysql back into an
    optional extra (the DB engines would gray out on a default install).
    """
    from pathlib import Path

    pyproject = (Path(__file__).parents[3] / "pyproject.toml").read_text(encoding="utf-8")
    deps = pyproject.split("[project.optional-dependencies]")[0]
    assert "psycopg" in deps and "pymysql" in deps
