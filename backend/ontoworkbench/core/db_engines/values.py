"""Connection values shared by dialects and reflection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConnValues:
    """Everything needed to reach a database (SQLite: database = path)."""

    host: str | None
    port: int | None
    database: str
    username: str | None
    password: str | None
