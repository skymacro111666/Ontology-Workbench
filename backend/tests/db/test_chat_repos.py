"""Chat session/message repos: owner scope, ordering, cascade delete."""

import uuid

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.db.models import Base
from ontoworkbench.db.repositories import ChatMessageRepository, ChatSessionRepository
from ontoworkbench.db.session import init_engine

UID = uuid.UUID(int=1)
OID = uuid.UUID(int=10)


@pytest.fixture()
def session() -> Session:
    """In-memory SQLite session (same shape as test_agent_token_repo.py).

    SQLite FK enforcement is off in this fixture, so cascade semantics are
    exercised through the repository's application-level delete.
    """
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s


def test_create_list_rename_delete(session: Session) -> None:
    """Create/list/get-owned/rename/delete roundtrip with owner scoping."""
    repo = ChatSessionRepository(session)
    s1 = repo.create(user_id=UID, ontology_id=OID, title="第一句用户消息截断")
    s2 = repo.create(user_id=UID, ontology_id=OID, title=None)
    session.commit()
    rows = repo.list_by_ontology(UID, OID)
    assert {r.id for r in rows} == {s1.id, s2.id}
    assert repo.get_owned(UID, OID, s1.id) is s1
    assert repo.get_owned(uuid.UUID(int=2), OID, s1.id) is None  # foreign user
    repo.rename(s1, "改名了")
    session.commit()
    assert repo.get_owned(UID, OID, s1.id).title == "改名了"
    assert repo.delete(UID, OID, s2.id) and not repo.delete(UID, OID, s2.id)


def test_messages_ordered_and_cascade(session: Session) -> None:
    """Messages stay ordered; deleting the session removes its messages."""
    srepo, mrepo = ChatSessionRepository(session), ChatMessageRepository(session)
    s = srepo.create(user_id=UID, ontology_id=OID, title="t")
    session.commit()
    for i in range(3):
        mrepo.append(s.id, "user" if i == 0 else "assistant", f"m{i}")
    session.commit()
    assert [m.content for m in mrepo.list_for(s.id)] == ["m0", "m1", "m2"]
    # message_count rides the list rows (scalar subquery)
    row = next(r for r in srepo.list_by_ontology(UID, OID) if r.id == s.id)
    assert row.message_count == 3
    srepo.delete(UID, OID, s.id)
    session.commit()
    assert mrepo.list_for(s.id) == []  # messages died with the session
