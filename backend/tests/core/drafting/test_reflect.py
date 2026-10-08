"""reflect_schema: SQLite real run + driver-missing error shape."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest

from ontoworkbench.core.db_engines import ENGINES, ConnValues
from ontoworkbench.core.drafting.reflect import reflect_schema
from ontoworkbench.core.errors import CoreError

DDL = """
CREATE TABLE customer (
    id INTEGER PRIMARY KEY,
    name VARCHAR(80) NOT NULL,
    vip BOOLEAN DEFAULT 0
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    status VARCHAR(20),
    notes TEXT,
    FOREIGN KEY (customer_id) REFERENCES customer(id)
);
"""


@pytest.fixture()
def shop_db(tmp_path: Path) -> str:
    """A real SQLite database with two FK-linked tables."""
    db = tmp_path / "shop.db"
    con = sqlite3.connect(db)
    con.executescript(DDL)
    con.commit()
    con.close()
    return str(db)


def _values(database: str) -> ConnValues:
    return ConnValues(host=None, port=None, database=database, username=None, password=None)


def test_reflect_sqlite_roundtrip(shop_db: str) -> None:
    """Tables, columns, nullability and FKs come back structured."""
    schema = reflect_schema(_values(shop_db), ENGINES["sqlite"])
    assert schema.database_name == "shop"
    by = {t.name: t for t in schema.tables}
    assert set(by) == {"customer", "orders"}
    fk = by["orders"].foreign_keys[0]
    assert (fk.column, fk.ref_table, fk.ref_column) == ("customer_id", "customer", "id")
    cols = {c.name: c for c in by["orders"].columns}
    assert cols["customer_id"].nullable is False
    assert cols["status"].nullable is True
    assert cols["id"].primary_key is True


def test_reflect_dumps_camel_case(shop_db: str) -> None:
    """Wire payloads are camelCase by contract."""
    schema = reflect_schema(_values(shop_db), ENGINES["sqlite"])
    dumped = schema.model_dump(by_alias=True)
    assert set(dumped) == {"databaseName", "tables"}
    assert set(dumped["tables"][0]) == {"name", "comment", "columns", "foreignKeys"}
    assert set(dumped["tables"][0]["columns"][0]) == {
        "name",
        "type",
        "nullable",
        "primaryKey",
        "unique",
        "comment",
    }


def test_driver_missing_hint() -> None:
    """The postgres dialect without its extra raises DB_DRIVER_MISSING with the extra name."""
    if importlib.util.find_spec("psycopg"):
        pytest.skip("psycopg installed on this box; CI exercises the branch")
    with pytest.raises(CoreError) as ei:
        reflect_schema(
            ConnValues(host="h", port=5432, database="d", username=None, password=None),
            ENGINES["postgres"],
        )
    assert ei.value.code == "DB_DRIVER_MISSING"
    assert "postgres" in (ei.value.hint or "")


def test_connect_failed(shop_db: str) -> None:
    """An unopenable database raises DB_CONNECT_FAILED."""
    with pytest.raises(CoreError) as ei:
        reflect_schema(_values("/nonexistent-dir/x.db"), ENGINES["sqlite"])
    assert ei.value.code == "DB_CONNECT_FAILED"
