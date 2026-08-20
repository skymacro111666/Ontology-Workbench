"""Engine/session factory; SQLite/PG selected solely by OW_DB_URL."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

_engine: Engine | None = None
SessionLocal: sessionmaker[Session] | None = None


def init_engine(db_url: str) -> Engine:
    """(Re)initialize the global engine and session factory; called once at startup."""
    global _engine, SessionLocal
    connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
    _engine = create_engine(db_url, connect_args=connect_args)
    SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a session; requires init_engine() first."""
    assert SessionLocal is not None, "init_engine() must run first"
    with SessionLocal() as session:
        yield session
