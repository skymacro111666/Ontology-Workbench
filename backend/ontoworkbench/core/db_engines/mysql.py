"""MySQL dialect (driver: pymysql, extra [mysql])."""

from __future__ import annotations

from urllib.parse import quote_plus

from ontoworkbench.core.db_engines.base import Dialect
from ontoworkbench.core.db_engines.values import ConnValues

TYPE_OVERRIDES: dict[str, str] = {
    "TINYTEXT": "xsd:string",
    "MEDIUMTEXT": "xsd:string",
    "LONGTEXT": "xsd:string",
    "YEAR": "xsd:integer",
    "BIT": "xsd:boolean",
    "ENUM": "xsd:string",
    "SET": "xsd:string",
}


def _url(v: ConnValues) -> str:
    """mysql+pymysql URL with credential escaping."""
    auth = ""
    if v.username:
        auth = quote_plus(v.username)
        if v.password:
            auth += f":{quote_plus(v.password)}"
        auth += "@"
    port = f":{v.port or 3306}"
    return f"mysql+pymysql://{auth}{v.host or 'localhost'}{port}/{v.database}"


DIALECT = Dialect(
    db_type="mysql",
    label="MySQL",
    extra_name="mysql",
    driver_module="pymysql",
    url=_url,
    default_port=3306,
    connect_args={"connect_timeout": 5},
    type_overrides=TYPE_OVERRIDES,
)
