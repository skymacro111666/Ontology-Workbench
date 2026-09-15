"""AgentTokenRepository: mint-less CRUD over the machine-credential table."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.auth.password import hash_password
from ontoworkbench.db.models import Base, User
from ontoworkbench.db.repositories import AgentTokenRepository, UserRepository
from ontoworkbench.db.session import init_engine


@pytest.fixture()
def session() -> Session:
    """Provide an in-memory SQLite session (same shape as test_repositories.py)."""
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # expire_on_commit=False mirrors production (db/session.py): after touch's
    # commit, SQLite re-reads would come back tz-naive and break comparisons.
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _user(session: Session) -> User:
    return UserRepository(session).create("admin", hash_password("long-enough-pw"))


def test_crud_roundtrip(session: Session) -> None:
    """Create, look up by hash/label, list, and delete one credential."""
    u = _user(session)
    repo = AgentTokenRepository(session)
    assert repo.count_any() == 0
    row = repo.create(u.id, "claude", "ab" * 32, "owag_cla")
    session.commit()
    assert repo.count_any() == 1
    assert repo.get_by_hash("ab" * 32) is row
    assert repo.get_by_label(u.id, "claude") is row
    assert [t.label for t in repo.list_by_user(u.id)] == ["claude"]
    assert repo.delete(u.id, row.id) is True
    session.commit()
    assert repo.count_any() == 0
    assert repo.delete(u.id, row.id) is False


def test_label_scope_is_per_user(session: Session) -> None:
    """The same label is legal for different users; lookups stay owner-scoped."""
    u1 = _user(session)
    u2 = UserRepository(session).create("second", hash_password("long-enough-pw"))
    session.commit()
    repo = AgentTokenRepository(session)
    repo.create(u1.id, "claude", "11" * 32, "owag_cla")
    repo.create(u2.id, "claude", "22" * 32, "owag_cla")  # same label, other user: legal
    session.commit()
    assert len(repo.list_by_user(u1.id)) == 1
    assert repo.get_by_label(u1.id, "claude").token_hash == "11" * 32


def test_touch_throttles_within_60s(session: Session) -> None:
    """Touch writes last_used_at only once per throttle window."""
    u = _user(session)
    repo = AgentTokenRepository(session)
    row = repo.create(u.id, "claude", "ab" * 32, "owag_cla")
    session.commit()
    recent = datetime.now(UTC) - timedelta(seconds=5)
    row.last_used_at = recent
    repo.touch(row)  # within the window: no write
    assert row.last_used_at == recent
    row.last_used_at = datetime.now(UTC) - timedelta(seconds=120)
    before = row.last_used_at
    repo.touch(row)
    assert row.last_used_at is not None and row.last_used_at > before
