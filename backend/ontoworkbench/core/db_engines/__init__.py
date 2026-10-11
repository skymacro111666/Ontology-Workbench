"""Database engine registry (spec §4): new engines register here.

Drivers ship as core dependencies, so `installed` is True for every
registered engine today; the flag (and the UI gray-out it feeds) stays as
the extension switch for a future engine whose driver cannot ship in a
wheel (GET /api/v1/db-connections/engines).
"""

from __future__ import annotations

import importlib.util

from ontoworkbench.core.db_engines.base import COMMON_TYPE_MAP, Dialect, map_type
from ontoworkbench.core.db_engines.clickhouse import DIALECT as _CLICKHOUSE
from ontoworkbench.core.db_engines.duckdb import DIALECT as _DUCKDB
from ontoworkbench.core.db_engines.mysql import DIALECT as _MYSQL
from ontoworkbench.core.db_engines.postgres import DIALECT as _POSTGRES
from ontoworkbench.core.db_engines.sqlite import DIALECT as _SQLITE
from ontoworkbench.core.db_engines.values import ConnValues

ENGINES: dict[str, Dialect] = {
    _POSTGRES.db_type: _POSTGRES,
    _MYSQL.db_type: _MYSQL,
    _SQLITE.db_type: _SQLITE,
    _DUCKDB.db_type: _DUCKDB,
    _CLICKHOUSE.db_type: _CLICKHOUSE,
}


def installed(dialect: Dialect) -> bool:
    """Whether the dialect's driver module can be imported."""
    return importlib.util.find_spec(dialect.driver_module) is not None


def classify_connect_error(exc: Exception) -> str:
    """Bucket a driver connect failure for the UI's human-readable line.

    Pattern-matches the driver message (DBAPI errors carry no stable
    cross-engine codes once SQLAlchemy wraps them); a miss lands in
    UNKNOWN with the raw text still shown alongside.
    """
    msg = str(exc).lower()
    # Order matters: pymysql's timeout message also says "can't connect".
    if "timeout" in msg or "timed out" in msg:
        return "TIMEOUT"
    if "connection refused" in msg or "can't connect" in msg or "cannot connect" in msg:
        return "REFUSED"
    if "password authentication" in msg or "authentication failed" in msg or "access denied" in msg:
        return "AUTH_FAILED"
    if "unknown database" in msg or ("database" in msg and "does not exist" in msg):
        return "DB_NOT_FOUND"
    # path-based engines (sqlite, duckdb): unopenable file under a missing dir
    if (
        "unable to open database file" in msg
        or "no such file or directory" in msg
        or "cannot open file" in msg
    ):
        return "PATH_NOT_FOUND"
    return "UNKNOWN"


__all__ = [
    "COMMON_TYPE_MAP",
    "ENGINES",
    "ConnValues",
    "Dialect",
    "classify_connect_error",
    "installed",
    "map_type",
]
