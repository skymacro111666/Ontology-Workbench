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


def test_touch_after_fresh_session_reload(session: Session) -> None:
    """Touch must not raise on a row reloaded in a new session (SQLite naive read).

    Regression: SQLite drops tzinfo when last_used_at is read back, so the
    second authenticated request (fresh session, non-NULL last_used_at)
    hit an aware-minus-naive TypeError inside touch().
    """
    u = _user(session)
    repo = AgentTokenRepository(session)
    row = repo.create(u.id, "claude", "ab" * 32, "owag_cla")
    session.commit()
    repo.touch(row)  # NULL path: seeds last_used_at

    fresh = Session(session.bind, expire_on_commit=False)
    try:
        reloaded = AgentTokenRepository(fresh).get_by_hash("ab" * 32)
        assert reloaded is not None and reloaded.last_used_at is not None
        fresh_repo = AgentTokenRepository(fresh)
        current = reloaded.last_used_at
        fresh_repo.touch(reloaded)  # reloaded row, within window: no raise, no write
        assert reloaded.last_used_at == current

        # Seed a stale timestamp while the row is still attached, for the
        # elapsed-window leg below (detached mutations never reach the DB).
        reloaded.last_used_at = datetime.now(UTC) - timedelta(seconds=120)
        fresh.commit()
    finally:
        fresh.close()

    fresh2 = Session(session.bind, expire_on_commit=False)
    try:
        stale_row = AgentTokenRepository(fresh2).get_by_hash("ab" * 32)
        assert stale_row is not None
        AgentTokenRepository(fresh2).touch(stale_row)  # reloaded, window elapsed: writes
        assert stale_row.last_used_at is not None and stale_row.last_used_at > reloaded.last_used_at
    finally:
        fresh2.close()
