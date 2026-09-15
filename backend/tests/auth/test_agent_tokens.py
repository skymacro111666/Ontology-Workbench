"""auth.agent_tokens: mint/hash/resolve + env seeding (spec D12)."""

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.auth import agent_tokens
from ontoworkbench.auth.password import hash_password
from ontoworkbench.db.models import Base, User
from ontoworkbench.db.repositories import AgentTokenRepository, UserRepository
from ontoworkbench.db.session import init_engine


@pytest.fixture()
def session() -> Session:
    """Provide an in-memory SQLite session (same shape as test_agent_token_repo.py)."""
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # expire_on_commit=False mirrors production (db/session.py): after touch's
    # commit, SQLite re-reads would come back tz-naive and break comparisons.
    with Session(engine, expire_on_commit=False) as s:
        yield s


def _user(session: Session) -> User:
    return UserRepository(session).create("admin", hash_password("long-enough-pw"))


def test_mint_shape() -> None:
    """Minted tokens carry the owag_ prefix, long entropy, and are unique."""
    t = agent_tokens.mint()
    assert t.startswith("owag_") and len(t) > 40
    assert agent_tokens.mint() != t  # unique per mint


def test_resolve_binds_account_and_label(session: Session) -> None:
    """A stored token resolves to its bound user and row label, and touches."""
    u = _user(session)
    token = agent_tokens.mint()
    repo = AgentTokenRepository(session)
    repo.create(u.id, "claude", agent_tokens.hash_token(token), token[:8])
    session.commit()
    got = agent_tokens.resolve(session, token)
    assert got is not None
    resolved_user, label = got
    assert resolved_user.id == u.id and label == "claude"
    row = repo.get_by_label(u.id, "claude")
    assert row is not None and row.last_used_at is not None  # resolve touches


def test_resolve_rejects_unknown_and_foreign(session: Session) -> None:
    """Unknown owag_ tokens and non-owag_ strings resolve to None."""
    _user(session)
    session.commit()
    assert agent_tokens.resolve(session, "owag_nope") is None
    assert agent_tokens.resolve(session, "some-jwt-looking-string") is None


def test_seed_insert_only(session: Session) -> None:
    """Env seeding imports well-formed entries once, skipping malformed/dupes."""
    u = _user(session)
    session.commit()
    imported = agent_tokens.seed_from_env(
        session, "claude:owag_abc123, ci:" + agent_tokens.mint() + ", bad-entry"
    )
    assert imported == ["claude", "ci"]  # malformed 'bad-entry' skipped
    again = agent_tokens.seed_from_env(session, "claude:owag_other")
    assert again == []  # existing label skipped (insert-only)
    repo = AgentTokenRepository(session)
    row = repo.get_by_label(u.id, "claude")
    assert row is not None and row.token_prefix == "owag_abc"[:8]


def test_seed_without_user_is_noop(session: Session) -> None:
    """With no user to bind, seeding imports nothing."""
    assert agent_tokens.seed_from_env(session, "claude:owag_abc123") == []
