"""MutationEventRepository: append-only journal writes + newest-first cursor reads."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.db.models import Base
from ontoworkbench.db.repositories import MutationEventRepository
from ontoworkbench.db.session import init_engine


@pytest.fixture()
def session() -> Session:
    """In-memory SQLite session (same shape as test_agent_token_repo.py)."""
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    # expire_on_commit=False mirrors production (db/session.py).
    with Session(engine, expire_on_commit=False) as s:
        yield s


def test_append_and_list_before(session: Session) -> None:
    """Events come back newest-first; before_id pages past the last seen id."""
    repo = MutationEventRepository(session)
    uid, oid = uuid4(), uuid4()
    for n in range(3):
        repo.append(
            user_id=uid,
            ontology_id=oid,
            action="entity.create",
            detail={"eid": f"ex:C{n}", "revisionAfter": n + 1},
        )
    session.commit()

    page = repo.list_before(user_id=uid, ontology_id=oid, limit=2)
    assert [e.detail["eid"] for e in page] == ["ex:C2", "ex:C1"]  # newest first

    older = repo.list_before(user_id=uid, ontology_id=oid, limit=2, before_id=page[-1].id)
    assert [e.detail["eid"] for e in older] == ["ex:C0"]

    # Another user's scope sees nothing.
    assert repo.list_before(user_id=uuid4(), ontology_id=oid, limit=10) == []


def test_append_defaults_and_fields(session: Session) -> None:
    """ontology_id is nullable (delete events), origin/source carry defaults."""
    repo = MutationEventRepository(session)
    row = repo.append(
        user_id=uuid4(),
        ontology_id=None,  # ontology.delete lands at user scope
        action="ontology.delete",
        detail={"ontologyId": str(uuid4()), "filename": "mini.ttl"},
    )
    session.commit()

    assert row.id is not None
    assert row.origin == "manual"
    assert row.source == "web"
    assert row.request_id is None
    assert row.created_at is not None
