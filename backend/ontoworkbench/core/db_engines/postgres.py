"""PostgreSQL dialect (driver: psycopg, extra [postgres])."""

from __future__ import annotations

from urllib.parse import quote_plus

from ontoworkbench.core.db_engines.base import Dialect
from ontoworkbench.core.db_engines.values import ConnValues

TYPE_OVERRIDES: dict[str, str] = {
    "JSONB": "xsd:string",
    "JSON": "xsd:string",
    "UUID": "xsd:string",
    "ARRAY": "xsd:string",
    "INET": "xsd:string",
    "CIDR": "xsd:string",
    "MACADDR": "xsd:string",
    "INTERVAL": "xsd:string",
}


def _url(v: ConnValues) -> str:
    """postgresql+psycopg URL with credential escaping."""
    auth = ""
    if v.username:
        auth = quote_plus(v.username)
        if v.password:
            auth += f":{quote_plus(v.password)}"
        auth += "@"
    port = f":{v.port}" if v.port else ""
    return f"postgresql+psycopg://{auth}{v.host or 'localhost'}{port}/{v.database}"


DIALECT = Dialect(
    db_type="postgres",
    label="PostgreSQL",
    extra_name="postgres",
    driver_module="psycopg",
    url=_url,
    connect_args={"connect_timeout": 5},
    type_overrides=TYPE_OVERRIDES,
)
