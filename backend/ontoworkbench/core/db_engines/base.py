"""Dialect protocol for database reflection (spec §4).

A dialect is a frozen value object: identity, URL building, connect args,
and type-mapping overrides. Drivers ship as core dependencies; adding an
engine = new module + one ENGINES registration — core never changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from ontoworkbench.core.db_engines.values import ConnValues

# Generic SQL type → XSD (spec §4). Unknown types fall back to xsd:string and
# let the LLM correction pass fix them.
COMMON_TYPE_MAP: dict[str, str] = {
    "VARCHAR": "xsd:string",
    "TEXT": "xsd:string",
    "CHAR": "xsd:string",
    "NCHAR": "xsd:string",
    "NVARCHAR": "xsd:string",
    "CLOB": "xsd:string",
    "INT": "xsd:integer",
    "INTEGER": "xsd:integer",
    "BIGINT": "xsd:integer",
    "SMALLINT": "xsd:integer",
    "TINYINT": "xsd:integer",
    "SERIAL": "xsd:integer",
    "BIGSERIAL": "xsd:integer",
    "DECIMAL": "xsd:decimal",
    "NUMERIC": "xsd:decimal",
    "DATE": "xsd:date",
    "TIME": "xsd:time",
    "DATETIME": "xsd:dateTime",
    "TIMESTAMP": "xsd:dateTime",
    "TIMESTAMPTZ": "xsd:dateTime",
    "BOOL": "xsd:boolean",
    "BOOLEAN": "xsd:boolean",
    "FLOAT": "xsd:double",
    "DOUBLE": "xsd:double",
    "REAL": "xsd:double",
}


@dataclass(frozen=True)
class Dialect:
    """One engine's reflection configuration."""

    db_type: str
    label: str
    driver_module: str  # import name checked for `installed`
    url: Callable[[ConnValues], str]
    default_port: int | None = None  # form prefill; None = path-based (sqlite, duckdb)
    connect_args: dict[str, object] = field(default_factory=dict)
    type_overrides: Mapping[str, str] = field(default_factory=dict)


# Wrapper shells that only modify nullability or dictionary encoding — the
# inner type is what maps (ClickHouse Nullable(Int64) → INT64 → integer).
_WRAPPER_TYPES = frozenset({"NULLABLE", "LOWCARDINALITY"})


def map_type(db_type_str: str, dialect: Dialect) -> str:
    """Normalize a DB type string to an XSD datatype.

    Length/precision decorations are stripped (VARCHAR(32) → VARCHAR),
    wrapper shells unwrap recursively (Nullable(Int64) → INT64), the
    dialect's overrides win over the common table, and anything unknown maps
    to xsd:string for the LLM correction pass to fix.
    """
    base = db_type_str.strip().upper()
    if "(" in base:
        head, inner = base.split("(", 1)
        head = head.strip()
        inner = inner.rstrip(")").strip()
        if head in _WRAPPER_TYPES and inner:
            return map_type(inner, dialect)
        base = head
    if base in dialect.type_overrides:
        return dialect.type_overrides[base]
    return COMMON_TYPE_MAP.get(base, "xsd:string")
