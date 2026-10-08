"""Database engine registry (spec §4): new engines register here.

`installed` reflects the driver's importability so the UI can gray out
engines whose extra is not installed (GET /api/v1/db-connections/engines).
"""

from __future__ import annotations

import importlib.util

from ontoworkbench.core.db_engines.base import COMMON_TYPE_MAP, Dialect, map_type
from ontoworkbench.core.db_engines.mysql import DIALECT as _MYSQL
from ontoworkbench.core.db_engines.postgres import DIALECT as _POSTGRES
from ontoworkbench.core.db_engines.sqlite import DIALECT as _SQLITE
from ontoworkbench.core.db_engines.values import ConnValues

ENGINES: dict[str, Dialect] = {
    _POSTGRES.db_type: _POSTGRES,
    _MYSQL.db_type: _MYSQL,
    _SQLITE.db_type: _SQLITE,
}


def installed(dialect: Dialect) -> bool:
    """Whether the dialect's driver module can be imported."""
    return importlib.util.find_spec(dialect.driver_module) is not None


__all__ = [
    "COMMON_TYPE_MAP",
    "ENGINES",
    "ConnValues",
    "Dialect",
    "installed",
    "map_type",
]
