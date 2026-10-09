"""Golden shop schema: reflect the eval fixture and check the full inventory.

The counts are hardcoded on purpose — docs/ai-drafting-eval.md promises this
exact shape to the manual eval protocol, so a fixture edit that changes the
inventory must update doc, fixture and this test together.
"""

import sqlite3
from pathlib import Path

import pytest

from ontoworkbench.core.db_engines import ENGINES, ConnValues
from ontoworkbench.core.drafting.reflect import reflect_schema

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "golden_shop.sql"

TABLES = {
    "customer",
    "orders",
    "order_items",
    "product",
    "category",
    "address",
    "payment",
    "user",
}

# (table, column, ref_table, ref_column) — one per declared FK, 7 total.
FKS = {
    ("customer", "ref_user_id", "user", "id"),
    ("orders", "customer_id", "customer", "id"),
    ("order_items", "order_id", "orders", "id"),
    ("order_items", "product_id", "product", "id"),
    ("product", "category_id", "category", "id"),
    ("address", "customer_id", "customer", "id"),
    ("payment", "order_id", "orders", "id"),
}


@pytest.fixture()
def golden_db(tmp_path: Path) -> str:
    """A real SQLite database built from the golden fixture DDL."""
    db = tmp_path / "golden_shop.db"
    con = sqlite3.connect(db)
    con.executescript(FIXTURE.read_text(encoding="utf-8"))
    con.commit()
    con.close()
    return str(db)


def _reflect(database: str):
    return reflect_schema(
        ConnValues(host=None, port=None, database=database, username=None, password=None),
        ENGINES["sqlite"],
    )


def test_golden_inventory(golden_db: str) -> None:
    """Every table, column family and FK from the eval doc reflects back."""
    schema = _reflect(golden_db)
    assert schema.database_name == "golden_shop"
    assert len(schema.tables) == 8
    by = {t.name: t for t in schema.tables}
    assert set(by) == TABLES

    # each table carries exactly one primary key column
    for name, table in by.items():
        pks = [c for c in table.columns if c.primary_key]
        assert len(pks) == 1, name

    # FK inventory: the declared 7 land on their tables with the right targets
    reflected = {
        (t.name, fk.column, fk.ref_table, fk.ref_column)
        for t in schema.tables
        for fk in t.foreign_keys
    }
    assert len(reflected) == 7
    assert reflected == FKS

    # spot columns: status / *_type families + UNIQUE members
    product = {c.name: c for c in by["product"].columns}
    assert product["sku"].unique is True
    assert product["status"].nullable is True
    assert product["price"].nullable is True
    orders = {c.name: c for c in by["orders"].columns}
    assert orders["status"].nullable is False
    assert orders["order_type"].nullable is True
    user = {c.name: c for c in by["user"].columns}
    assert user["email"].unique is True
    assert user["username"].unique is True
    assert user["role"].nullable is True
