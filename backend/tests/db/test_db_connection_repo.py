"""DbConnectionRepository: owner-scoped connection profiles."""

import uuid

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.auth.password import hash_password
from ontoworkbench.db.models import Base
from ontoworkbench.db.repositories import DbConnectionRepository, UserRepository
from ontoworkbench.db.session import init_engine

UID = uuid.UUID(int=1)
OTHER = uuid.UUID(int=2)


@pytest.fixture()
def session() -> Session:
    """Provide an in-memory SQLite session (same shape as test_agent_token_repo.py)."""
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _user(session: Session) -> None:
    UserRepository(session).create("admin", hash_password("long-enough-pw"))


def _conn(repo: DbConnectionRepository, name: str = "prod-pg"):
    return repo.create(
        user_id=UID,
        name=name,
        db_type="postgres",
        host="db.internal",
        port=5432,
        database_name="app",
        username="app",
        password_cipher="gAAA-some-ciphertext",
    )


def test_create_list_delete_owner_scoped(session: Session) -> None:
    """Rows are visible and deletable only for their owner."""
    _user(session)
    repo = DbConnectionRepository(session)
    row = _conn(repo)
    session.commit()
    assert [r.name for r in repo.list_by_user(UID)] == ["prod-pg"]
    assert repo.list_by_user(OTHER) == []
    assert repo.get_owned(OTHER, row.id) is None
    assert repo.get_owned(UID, row.id) is row
    assert repo.delete(UID, row.id) is True
    assert repo.delete(UID, row.id) is False


def test_update_changes_fields(session: Session) -> None:
    """Update replaces given fields only."""
    _user(session)
    repo = DbConnectionRepository(session)
    row = _conn(repo)
    session.commit()
    repo.update(row, host="db2.internal", port=5433)
    session.commit()
    fresh = repo.get_owned(UID, row.id)
    assert (fresh.host, fresh.port, fresh.database_name) == ("db2.internal", 5433, "app")
