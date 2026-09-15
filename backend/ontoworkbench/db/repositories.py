"""Repository abstractions over ORM; the only DB access surface."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ontoworkbench.db.models import (
    AgentToken,
    LintRule,
    Ontology,
    OntologyLayout,
    OntologyValidationShape,
    User,
)


def _now_utc() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


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

    def first(self) -> User | None:
        """Get the earliest-created user (the Phase 1 admin).

        Returns:
            User if any exist, None otherwise.
        """
        stmt = select(User).order_by(User.created_at).limit(1)
        return self._s.scalars(stmt).first()

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

    def update_password(self, user_id: UUID, password_hash: str) -> None:
        """Replace a user's password hash.

        Args:
            user_id: User to update.
            password_hash: New hashed password.
        """
        u = self._s.get(User, user_id)
        if u is not None:
            u.password_hash = password_hash
            self._s.commit()


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

    def update(self, ontology_id: UUID, **fields: object) -> Ontology | None:
        """Update fields of an ontology row by id; None when unknown.

        Args:
            ontology_id: UUID of the ontology to update.
            **fields: Column values to set (file_hash, class_count, ...).

        Returns:
            The updated Ontology, or None when the id does not exist.
        """
        o = self.get(ontology_id)
        if not o:
            return None
        for key, value in fields.items():
            setattr(o, key, value)
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


class LayoutRepository:
    """Access to ontology_layouts: whole-map canvas position storage."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._s = session

    def get(self, ontology_id: UUID) -> OntologyLayout | None:
        """Get the layout row for an ontology.

        Args:
            ontology_id: UUID of the ontology.

        Returns:
            OntologyLayout if saved, None otherwise.
        """
        return self._s.get(OntologyLayout, ontology_id)

    def upsert(self, ontology_id: UUID, positions: dict) -> OntologyLayout:
        """Overwrite the whole position map for an ontology (no merge).

        Args:
            ontology_id: UUID of the ontology.
            positions: Full {eid: {x, y}} map.

        Returns:
            The saved OntologyLayout row.
        """
        row = self.get(ontology_id)
        if row:
            row.positions = positions
        else:
            row = OntologyLayout(ontology_id=ontology_id, positions=positions)
            self._s.add(row)
        self._s.commit()
        return row

    def delete(self, ontology_id: UUID) -> None:
        """Drop the layout row for an ontology (reset to auto layout).

        Args:
            ontology_id: UUID of the ontology.
        """
        row = self.get(ontology_id)
        if row:
            self._s.delete(row)
            self._s.commit()


class LintRuleRepository:
    """Access to lint_rules: per-ontology builtin toggles + custom rules."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._s = session

    def list_for(self, ontology_id: UUID) -> list[LintRule]:
        """All config rows for an ontology, insertion-ordered.

        Args:
            ontology_id: UUID of the ontology.

        Returns:
            The LintRule rows (builtin toggles and custom rules alike).
        """
        stmt = (
            select(LintRule)
            .where(LintRule.ontology_id == ontology_id)
            .order_by(LintRule.created_at)
        )
        return list(self._s.scalars(stmt))

    def replace_all(self, ontology_id: UUID, disabled: list[str], customs: list[dict]) -> None:
        """Whole-config overwrite (PUT semantics; idempotent, no locks).

        Args:
            ontology_id: UUID of the ontology.
            disabled: builtin rule ids to switch off.
            customs: custom rule dicts (name/severity/sparql/enabled).
        """
        for row in self.list_for(ontology_id):
            self._s.delete(row)
        for key in disabled:
            self._s.add(LintRule(ontology_id=ontology_id, kind="builtin", key=key, enabled=False))
        for c in customs:
            self._s.add(
                LintRule(
                    ontology_id=ontology_id,
                    kind="custom",
                    name=c["name"],
                    severity=c["severity"],
                    sparql=c["sparql"],
                    enabled=c.get("enabled", True),
                )
            )
        self._s.commit()


class ValidationShapesRepository:
    """Access to validation_shapes: one editable SHACL source per ontology."""

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._s = session

    def get(self, ontology_id: UUID) -> OntologyValidationShape | None:
        """Get the shapes row for an ontology.

        Args:
            ontology_id: UUID of the ontology.

        Returns:
            OntologyValidationShape if saved, None otherwise.
        """
        stmt = select(OntologyValidationShape).where(
            OntologyValidationShape.ontology_id == ontology_id
        )
        return self._s.scalar(stmt)

    def upsert(self, ontology_id: UUID, source: str) -> OntologyValidationShape:
        """Overwrite the shapes source for an ontology (one row, no merge).

        Args:
            ontology_id: UUID of the ontology.
            source: Full SHACL shapes graph text.

        Returns:
            The saved OntologyValidationShape row.
        """
        row = self.get(ontology_id)
        if row:
            row.source = source
        else:
            row = OntologyValidationShape(ontology_id=ontology_id, source=source)
            self._s.add(row)
        self._s.commit()
        return row


class AgentTokenRepository:
    """Access to agent_tokens (machine credentials, spec D12)."""

    _TOUCH_THROTTLE_S = 60

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._s = session

    def count_any(self) -> int:
        """Total rows across users — the MCP mount condition."""
        return len(self._s.scalars(select(AgentToken.id)).all())

    def get_by_label(self, user_id: UUID, label: str) -> AgentToken | None:
        """Get an agent token by owner and label.

        Args:
            user_id: UUID of the owning user.
            label: Credential label, unique per user.

        Returns:
            AgentToken if found, None otherwise.
        """
        return self._s.scalar(
            select(AgentToken).where(AgentToken.user_id == user_id, AgentToken.label == label)
        )

    def get_by_hash(self, token_hash: str) -> AgentToken | None:
        """Get an agent token by hash (the request-auth lookup).

        Args:
            token_hash: SHA-256 hex digest, globally unique.

        Returns:
            AgentToken if found, None otherwise.
        """
        return self._s.scalar(select(AgentToken).where(AgentToken.token_hash == token_hash))

    def list_by_user(self, user_id: UUID) -> list[AgentToken]:
        """List a user's agent tokens, oldest first.

        Args:
            user_id: UUID of the owning user.

        Returns:
            List of the user's AgentToken rows.
        """
        stmt = (
            select(AgentToken).where(AgentToken.user_id == user_id).order_by(AgentToken.created_at)
        )
        return list(self._s.scalars(stmt).all())

    def create(self, user_id: UUID, label: str, token_hash: str, token_prefix: str) -> AgentToken:
        """Stage a new agent token row (committed by the caller).

        Args:
            user_id: UUID of the owning user.
            label: Credential label, unique per user.
            token_hash: SHA-256 hex digest of the minted token.
            token_prefix: Display prefix for the credential list.

        Returns:
            The staged AgentToken instance.
        """
        row = AgentToken(
            user_id=user_id, label=label, token_hash=token_hash, token_prefix=token_prefix
        )
        self._s.add(row)
        return row

    def delete(self, user_id: UUID, token_id: UUID) -> bool:
        """Delete an agent token only if it belongs to the given user.

        Args:
            user_id: UUID of the requesting user.
            token_id: UUID of the token to delete.

        Returns:
            True if a row was deleted, False when unknown or foreign.
        """
        row = self._s.get(AgentToken, token_id)
        if row is None or row.user_id != user_id:
            return False
        self._s.delete(row)
        return True

    def touch(self, row: AgentToken) -> None:
        """Update last_used_at at most once per minute (audit, not auth)."""
        now = _now_utc()
        if row.last_used_at is not None and (now - row.last_used_at).total_seconds() < (
            self._TOUCH_THROTTLE_S
        ):
            return
        row.last_used_at = now
        self._s.commit()
