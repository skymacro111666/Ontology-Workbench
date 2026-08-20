"""Repository abstractions over ORM; the only DB access surface."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ontoworkbench.db.models import Ontology, User


class UserRepository:
    """Access to users table."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._s = session

    def count(self) -> int:
        """Return the total number of users in the database.

        Returns:
            Total count of users.
        """
        return len(self._s.scalars(select(User.id)).all())

    def get(self, user_id: UUID) -> User | None:
        """Get a user by ID.

        Args:
            user_id: UUID of the user to retrieve.

        Returns:
            User if found, None otherwise.
        """
        return self._s.get(User, user_id)

    def get_by_username(self, username: str) -> User | None:
        """Get a user by username.

        Args:
            username: Username to search for.

        Returns:
            User if found, None otherwise.
        """
        return self._s.scalar(select(User).where(User.username == username))

    def create(self, username: str, password_hash: str) -> User:
        """Create a new user.

        Args:
            username: Unique username.
            password_hash: Hashed password.

        Returns:
            The created User instance.
        """
        u = User(username=username, password_hash=password_hash)
        self._s.add(u)
        self._s.commit()
        return u


class OntologyRepository:
    """Access to ontologies registry."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._s = session

    def create(self, owner_user_id: UUID, **fields: object) -> Ontology:
        """Create a new ontology owned by a user.

        Args:
            owner_user_id: UUID of the user who will own this ontology.
            **fields: Additional ontology fields (filename, storage_path, etc.).

        Returns:
            The created Ontology instance.
        """
        o = Ontology(owner_user_id=owner_user_id, **fields)
        self._s.add(o)
        self._s.commit()
        return o

    def list_by_owner(self, owner_user_id: UUID) -> list[Ontology]:
        """List all ontologies owned by a user, ordered by creation date (newest first).

        Args:
            owner_user_id: UUID of the user.

        Returns:
            List of ontologies owned by the user, newest first.
        """
        stmt = (
            select(Ontology)
            .where(Ontology.owner_user_id == owner_user_id)
            .order_by(Ontology.created_at.desc())
        )
        return list(self._s.scalars(stmt))

    def get(self, ontology_id: UUID) -> Ontology | None:
        """Get an ontology by ID.

        Args:
            ontology_id: UUID of the ontology.

        Returns:
            Ontology if found, None otherwise.
        """
        return self._s.get(Ontology, ontology_id)

    def get_owned(self, owner_user_id: UUID, ontology_id: UUID) -> Ontology | None:
        """Get an ontology only if it belongs to the specified user.

        Enforces owner isolation: returns None if the ontology exists
        but belongs to a different user.

        Args:
            owner_user_id: UUID of the user who should own the ontology.
            ontology_id: UUID of the ontology to retrieve.

        Returns:
            Ontology if found and owned by the user, None otherwise.
        """
        o = self.get(ontology_id)
        return o if o and o.owner_user_id == owner_user_id else None

    def find_by_filename(self, owner_user_id: UUID, filename: str) -> Ontology | None:
        """Find an ontology by filename for a specific owner.

        Args:
            owner_user_id: UUID of the user.
            filename: Filename to search for.

        Returns:
            Ontology if found and owned by the user, None otherwise.
        """
        stmt = select(Ontology).where(
            Ontology.owner_user_id == owner_user_id, Ontology.filename == filename
        )
        return self._s.scalar(stmt)

    def delete(self, ontology_id: UUID) -> None:
        """Delete an ontology by ID.

        Args:
            ontology_id: UUID of the ontology to delete.
        """
        o = self.get(ontology_id)
        if o:
            self._s.delete(o)
            self._s.commit()
