"""Schema-level tests: constraints fire as designed."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.session import init_engine


@pytest.fixture()
def db() -> Session:
    """Create an in-memory engine and yield a session bound to it."""
    engine = init_engine("sqlite:///:memory:")
    from ontoworkbench.db.models import Base

    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_unique_username(db: Session) -> None:
    """Test that duplicate usernames raise IntegrityError on commit."""
    db.add(User(username="alice", password_hash="x"))
    db.add(User(username="alice", password_hash="y"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_unique_owner_filename(db: Session) -> None:
    """Test that duplicate (owner, filename) pairs raise IntegrityError."""
    u = User(username="alice", password_hash="x")
    db.add(u)
    db.commit()
    for _ in range(2):
        db.add(
            Ontology(
                owner_user_id=u.id,
                filename="pizza.ttl",
                storage_path="u/p",
                format="turtle",
            )
        )
    with pytest.raises(IntegrityError):
        db.commit()
