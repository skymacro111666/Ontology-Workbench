"""DuckDB dialect (drivers: duckdb + duckdb-engine, core dependencies).

File-based OLAP like sqlite: the database field carries the file path,
host/port/username stay empty. FK reflection is supported by duckdb-engine,
so the drafting pipeline's FK-affinity batching works unchanged. Primary
keys are NOT reflected (duckdb-engine limitation as of 0.17) — columns come
back with primaryKey false; harmless for batching, noted in the tests.
"""

from __future__ import annotations

from ontoworkbench.core.db_engines.base import Dialect
from ontoworkbench.core.db_engines.values import ConnValues

TYPE_OVERRIDES: dict[str, str] = {
    # int128 and the unsigned family stay integers on the wire
    "HUGEINT": "xsd:integer",
    "UBIGINT": "xsd:integer",
    "UINTEGER": "xsd:integer",
    "USMALLINT": "xsd:integer",
    "UTINYINT": "xsd:integer",
    "UUID": "xsd:string",
    "ENUM": "xsd:string",
    # BIT here is a bitstring, not MySQL's boolean-sized BIT
    "BIT": "xsd:string",
    "BLOB": "xsd:string",
    "TIMESTAMP WITH TIME ZONE": "xsd:dateTime",
    "TIMESTAMP_S": "xsd:dateTime",
    "TIMESTAMP_MS": "xsd:dateTime",
    "TIMESTAMP_NS": "xsd:dateTime",
}


def _url(v: ConnValues) -> str:
    """DuckDB URL; the database field is an absolute or relative file path."""
    return f"duckdb:///{v.database}"


DIALECT = Dialect(
    db_type="duckdb",
    label="DuckDB",
    driver_module="duckdb",
    url=_url,
    default_port=None,  # path-based, like sqlite
    connect_args={},
    type_overrides=TYPE_OVERRIDES,
)
