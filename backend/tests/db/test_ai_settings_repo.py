"""AiSettingsRepository: per-user single-row upsert semantics."""

import uuid

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.auth.password import hash_password
from ontoworkbench.db.models import Base, User
from ontoworkbench.db.repositories import AiSettingsRepository, UserRepository
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


def _user(session: Session, uid: uuid.UUID = UID) -> User:
    """A user row so the FK target exists."""
    return UserRepository(session).create(f"u{uid.int}", hash_password("long-enough-pw"))


def test_upsert_creates_then_updates(session: Session) -> None:
    """A second upsert for the same user updates in place, never a second row."""
    _user(session)
    repo = AiSettingsRepository(session)
    repo.upsert(user_id=UID, provider="anthropic", model="m1")
    row = repo.upsert(user_id=UID, model="m2")
    session.commit()
    assert repo.get(UID) is row
    assert row.model == "m2" and row.provider == "anthropic"
    assert repo.get(OTHER) is None


def test_upsert_preserves_omitted_fields(session: Session) -> None:
    """A partial upsert keeps previously stored values."""
    _user(session)
    repo = AiSettingsRepository(session)
    repo.upsert(user_id=UID, provider="openai", base_url="https://api.test/v1", model="m1")
    repo.upsert(user_id=UID, model="m2")
    session.commit()
    row = repo.get(UID)
    assert row.model == "m2" and row.base_url == "https://api.test/v1"
