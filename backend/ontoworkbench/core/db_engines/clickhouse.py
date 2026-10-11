"""ClickHouse dialect (clickhouse-connect + clickhouse-sqlalchemy; HTTP, 8123).

No FK constraints exist in ClickHouse, so reflection returns none — the
drafting pipeline's FK-affinity batching degrades to per-table batches.
ClickHouse's wrapper types (Nullable(...), LowCardinality(...)) are handled
generically by map_type's wrapper strip; the overrides below cover what the
inner/bare types need.
"""

from __future__ import annotations

from urllib.parse import quote_plus

from ontoworkbench.core.db_engines.base import Dialect
from ontoworkbench.core.db_engines.values import ConnValues

TYPE_OVERRIDES: dict[str, str] = {
    "STRING": "xsd:string",
    "BOOL": "xsd:boolean",
    # fixed-width ints outside the common names
    "INT8": "xsd:integer",
    "INT16": "xsd:integer",
    "INT32": "xsd:integer",
    "INT64": "xsd:integer",
    "UINT8": "xsd:integer",
    "UINT16": "xsd:integer",
    "UINT32": "xsd:integer",
    "UINT64": "xsd:integer",
    "UINT128": "xsd:integer",
    "UINT256": "xsd:integer",
    "INT128": "xsd:integer",
    "INT256": "xsd:integer",
    "FLOAT32": "xsd:double",
    "FLOAT64": "xsd:double",
    "DATE32": "xsd:date",
    "DATETIME64": "xsd:dateTime",
    "ENUM8": "xsd:string",
    "ENUM16": "xsd:string",
    "UUID": "xsd:string",
    "IPV4": "xsd:string",
    "IPV6": "xsd:string",
    "JSON": "xsd:string",
    # nested containers have no XSD shape — stringify
    "ARRAY": "xsd:string",
    "MAP": "xsd:string",
    "TUPLE": "xsd:string",
    "NESTED": "xsd:string",
    "POINT": "xsd:string",
    "RING": "xsd:string",
}


def _url(v: ConnValues) -> str:
    """clickhousedb+connect URL (official HTTP driver) with credential escaping."""
    auth = ""
    if v.username:
        auth = quote_plus(v.username)
        if v.password:
            auth += f":{quote_plus(v.password)}"
        auth += "@"
    port = f":{v.port or 8123}"
    return f"clickhousedb+connect://{auth}{v.host or 'localhost'}{port}/{v.database}"


DIALECT = Dialect(
    db_type="clickhouse",
    label="ClickHouse",
    driver_module="clickhouse_connect",
    url=_url,
    default_port=8123,
    connect_args={"connect_timeout": 5},
    type_overrides=TYPE_OVERRIDES,
)
