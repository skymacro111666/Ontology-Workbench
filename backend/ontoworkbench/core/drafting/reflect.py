"""SQLAlchemy-based schema reflection (spec §5.2).

Read-only by construction: the inspector only issues catalog queries, never
user SQL. Credentials live in memory for the call and are dropped with the
engine. System tables (sqlite_*) are skipped.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.engine import Inspector

from ontoworkbench.core.db_engines import ConnValues, Dialect
from ontoworkbench.core.drafting.models import (
    ColumnSpec,
    ForeignKeySpec,
    SchemaModel,
    TableSpec,
)
from ontoworkbench.core.errors import CoreError


def _columns(inspector: Inspector, table: str) -> list[ColumnSpec]:
    """Column specs incl. PK and single-column UNIQUE flags."""
    pk = set(inspector.get_pk_constraint(table).get("constrained_columns") or [])
    uniques: set[str] = set()
    for ix in inspector.get_indexes(table):
        cols = ix.get("column_names") or []
        if ix.get("unique") and len(cols) == 1:
            uniques.add(cols[0])
    out: list[ColumnSpec] = []
    for col in inspector.get_columns(table):
        out.append(
            ColumnSpec(
                name=col["name"],
                type_=str(col["type"]),
                nullable=bool(col.get("nullable", True)),
                primary_key=col["name"] in pk,
                unique=col["name"] in uniques,
            )
        )
    return out


def _comment(inspector: Inspector, table: str) -> str | None:
    """Table comment where the backend supports one (SQLite: none)."""
    try:
        c = inspector.get_table_comment(table).get("text")
    except (NotImplementedError, sa.exc.NoInspectionAvailable, KeyError):
        return None
    return c or None


def reflect_schema(values: ConnValues, dialect: Dialect) -> SchemaModel:
    """Reflect tables/columns/FKs into a SchemaModel; engine disposed after."""
    try:
        engine = create_engine(dialect.url(values), connect_args=dict(dialect.connect_args))
    except ModuleNotFoundError as e:
        raise CoreError(
            "DB_DRIVER_MISSING",
            f"driver for {dialect.db_type} is not installed",
            hint=f"pip install 'ontology-workbench[{dialect.extra_name}]'",
        ) from e
    try:
        inspector = sa.inspect(engine)
        tables: list[TableSpec] = []
        for name in inspector.get_table_names():
            if name.startswith("sqlite_"):
                continue
            fks: list[ForeignKeySpec] = []
            for fk in inspector.get_foreign_keys(name):
                referred = fk.get("referred_table", "")
                for local, remote in zip(
                    fk.get("constrained_columns") or [],
                    fk.get("referred_columns") or [],
                    strict=False,
                ):
                    fks.append(ForeignKeySpec(column=local, ref_table=referred, ref_column=remote))
            tables.append(
                TableSpec(
                    name=name,
                    comment=_comment(inspector, name),
                    columns=_columns(inspector, name),
                    foreign_keys=fks,
                )
            )
        return SchemaModel(database_name=_db_label(values, dialect), tables=tables)
    except sa.exc.OperationalError as e:
        raise CoreError(
            "DB_CONNECT_FAILED", "could not connect to the database", hint=str(e)[:300]
        ) from e
    finally:
        engine.dispose()


def _db_label(values: ConnValues, dialect: Dialect) -> str:
    """A short database name for labels and default namespaces."""
    name = values.database.rstrip("/").rsplit("/", 1)[-1]
    for suffix in (".db", ".sqlite", ".sqlite3"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return name or values.database
