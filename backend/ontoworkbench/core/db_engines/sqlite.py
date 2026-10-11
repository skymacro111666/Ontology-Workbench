"""SQLite dialect (stdlib driver; the test and demo carrier)."""

from __future__ import annotations

from ontoworkbench.core.db_engines.base import Dialect
from ontoworkbench.core.db_engines.values import ConnValues


def _url(v: ConnValues) -> str:
    """Sqlite URL over an absolute or relative path."""
    return f"sqlite:///{v.database}"


DIALECT = Dialect(
    db_type="sqlite",
    label="SQLite",
    driver_module="sqlite3",
    url=_url,
    connect_args={},
)
