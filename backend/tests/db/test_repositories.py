"""Repository behaviour tests (in-memory sqlite)."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from ontoworkbench.db.models import Base
from ontoworkbench.db.repositories import OntologyRepository, UserRepository
from ontoworkbench.db.session import init_engine


@pytest.fixture()
def session() -> Session:
    """Provide an in-memory SQLite session for testing.

    Creates tables on setup and yields a session for use in tests.
    """
    engine = init_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_user_roundtrip(session: Session) -> None:
    """Test UserRepository create, count, and get_by_username operations.

    Creates a user and verifies it can be retrieved and counted correctly.
    """
    repo = UserRepository(session)
    u = repo.create("alice", "hash")
    assert repo.count() == 1
    assert repo.get_by_username("alice").id == u.id


def test_ontology_owner_isolation(session: Session) -> None:
    """Test OntologyRepository owner isolation enforcement.

    Creates two users and an ontology for one, verifying that:
    - The other user cannot access it via get_owned (returns None)
    - The owner can retrieve it via get_owned
    - The owner can find it by filename
    """
    users = UserRepository(session)
    a = users.create("alice", "x")
    b = users.create("bob", "x")
    repos = OntologyRepository(session)
    o = repos.create(a.id, filename="pizza.ttl", storage_path="p", format="turtle", file_hash="h")
    assert repos.get_owned(b.id, o.id) is None  # invisible to others
    assert repos.get_owned(a.id, o.id).filename == "pizza.ttl"
    assert repos.find_by_filename(a.id, "pizza.ttl").id == o.id


def test_ontology_update_fields(session: Session) -> None:
    """update() changes columns and persists; unknown id returns None."""
    users = UserRepository(session)
    repos = OntologyRepository(session)
    u = users.create("alice", "x")
    o = repos.create(u.id, filename="f.ttl", storage_path="p", format="turtle", file_hash="h1")
    updated = repos.update(o.id, file_hash="h2", class_count=5)
    assert updated is not None and updated.file_hash == "h2" and updated.class_count == 5
    assert repos.get(o.id).file_hash == "h2"  # 持久化,不只是内存对象
    assert repos.update(uuid4(), file_hash="x") is None
