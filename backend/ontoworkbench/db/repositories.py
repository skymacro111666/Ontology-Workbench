"""Repository abstractions over ORM; the only DB access surface."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ontoworkbench.db.models import (
    AgentToken,
    AiSetting,
    ChatMessage,
    ChatSession,
    DbConnection,
    LintRule,
    MutationEvent,
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
        """Update last_used_at at most once per minute (audit, not auth).

        A tz-naive stored timestamp (SQLite drops the offset on read) is
        re-anchored to UTC before the throttle comparison.
        """
        now = _now_utc()
        last = row.last_used_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)  # stored wall-clock is UTC
            if (now - last).total_seconds() < self._TOUCH_THROTTLE_S:
                return
        row.last_used_at = now
        self._s.commit()


class MutationEventRepository:
    """Append-only writes + newest-first cursor reads for mutation_events.

    The Registry journal (Phase 1): events ride the caller's session, so a
    mutation and its journal row commit or roll back together (fail-closed —
    no edit lands without its event). There is deliberately no update or
    delete path.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the repository with a SQLAlchemy session.

        Args:
            session: SQLAlchemy database session.
        """
        self._session = session

    def append(
        self,
        *,
        user_id: UUID,
        ontology_id: UUID | None,
        action: str,
        detail: dict[str, Any],
        origin: str = "manual",
        source: str = "web",
        request_id: str | None = None,
    ) -> MutationEvent:
        """Add one journal row; flush so id/created_at are readable in-transaction."""
        row = MutationEvent(
            user_id=user_id,
            ontology_id=ontology_id,
            action=action,
            detail=detail,
            origin=origin,
            source=source,
            request_id=request_id,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_before(
        self,
        *,
        user_id: UUID,
        ontology_id: UUID,
        limit: int = 50,
        before_id: int | None = None,
    ) -> list[MutationEvent]:
        """Newest-first page of the ontology's journal; before_id pages past it."""
        stmt = (
            select(MutationEvent)
            .where(
                MutationEvent.user_id == user_id,
                MutationEvent.ontology_id == ontology_id,
            )
            .order_by(MutationEvent.id.desc())
            .limit(limit)
        )
        if before_id is not None:
            stmt = stmt.where(MutationEvent.id < before_id)
        return list(self._session.scalars(stmt))


class AiSettingsRepository:
    """Per-user single-row ModelProvider settings (upsert semantics)."""

    def __init__(self, session: Session) -> None:
        """Initialize with the shared session; callers own commit."""
        self._s = session

    def get(self, user_id: UUID) -> AiSetting | None:
        """Return the user's settings row, if any."""
        return self._s.scalars(select(AiSetting).where(AiSetting.user_id == user_id)).first()

    def upsert(self, *, user_id: UUID, **fields: Any) -> AiSetting:
        """Create or partially update the single row; omitted fields keep their values."""
        row = self.get(user_id)
        if row is None:
            row = AiSetting(user_id=user_id)
            self._s.add(row)
        for key, value in fields.items():
            if hasattr(AiSetting, key):
                setattr(row, key, value)
        self._s.flush()
        return row


class DbConnectionRepository:
    """Owner-scoped database connection profiles."""

    def __init__(self, session: Session) -> None:
        """Initialize with the shared session; callers own commit."""
        self._s = session

    def list_by_user(self, user_id: UUID) -> list[DbConnection]:
        """The user's saved connections, newest first."""
        stmt = (
            select(DbConnection)
            .where(DbConnection.user_id == user_id)
            .order_by(DbConnection.created_at.desc())
        )
        return list(self._s.scalars(stmt))

    def get_owned(self, user_id: UUID, connection_id: UUID) -> DbConnection | None:
        """Fetch one connection only when it belongs to the user."""
        return self._s.scalars(
            select(DbConnection).where(
                DbConnection.user_id == user_id, DbConnection.id == connection_id
            )
        ).first()

    def create(self, *, user_id: UUID, **fields: Any) -> DbConnection:
        """Stage a new connection row (caller commits)."""
        row = DbConnection(user_id=user_id, **fields)
        self._s.add(row)
        self._s.flush()
        return row

    def update(self, row: DbConnection, **fields: Any) -> None:
        """Replace the given fields on an owned row (caller commits)."""
        for key, value in fields.items():
            if hasattr(DbConnection, key):
                setattr(row, key, value)
        self._s.flush()

    def delete(self, user_id: UUID, connection_id: UUID) -> bool:
        """Hard-delete an owned connection; False for unknown/foreign ids."""
        row = self.get_owned(user_id, connection_id)
        if row is None:
            return False
        self._s.delete(row)
        self._s.flush()
        return True


class ChatSessionRepository:
    """Owner-scoped chat sessions per ontology (spec-2 §4).

    Rows are created lazily by the SSE endpoint's first successful send;
    delete cascades messages explicitly (SQLite runs without FK enforcement
    in dev/test, so the repository owns the cascade semantics).
    """

    def __init__(self, session: Session) -> None:
        """Bind to the caller's session (caller owns commit)."""
        self._s = session

    def list_by_ontology(self, user_id: UUID, ontology_id: UUID) -> list[ChatSession]:
        """Sessions newest-first; message_count rides each row as a subquery."""
        count = (
            select(func.count(ChatMessage.id))
            .where(ChatMessage.session_id == ChatSession.id)
            .scalar_subquery()
        )
        rows = self._s.execute(
            select(ChatSession, count)
            .where(ChatSession.user_id == user_id, ChatSession.ontology_id == ontology_id)
            .order_by(ChatSession.updated_at.desc())
        ).all()
        out: list[ChatSession] = []
        for s, n in rows:
            s.message_count = n  # type: ignore[attr-defined]
            out.append(s)
        return out

    def get_owned(self, user_id: UUID, ontology_id: UUID, session_id: UUID) -> ChatSession | None:
        """The session when it belongs to (user, ontology); None otherwise."""
        return self._s.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.user_id == user_id,
                ChatSession.ontology_id == ontology_id,
            )
        )

    def create(self, user_id: UUID, ontology_id: UUID, title: str | None) -> ChatSession:
        """Stage a new session (caller commits)."""
        row = ChatSession(user_id=user_id, ontology_id=ontology_id, title=title)
        self._s.add(row)
        self._s.flush()
        return row

    def rename(self, row: ChatSession, title: str) -> None:
        """Set the title (touches updated_at via onupdate)."""
        row.title = title

    def touch(self, row: ChatSession) -> None:
        """Bump updated_at so the list re-sorts to the top."""
        row.updated_at = _now_utc()

    def delete(self, user_id: UUID, ontology_id: UUID, session_id: UUID) -> bool:
        """Delete an owned session and its messages; False for unknown ids."""
        row = self.get_owned(user_id, ontology_id, session_id)
        if row is None:
            return False
        self._s.execute(delete(ChatMessage).where(ChatMessage.session_id == session_id))
        self._s.delete(row)
        self._s.flush()
        return True


class ChatMessageRepository:
    """Ordered chat turns of one session (spec-2 §4)."""

    def __init__(self, session: Session) -> None:
        """Bind to the caller's session (caller owns commit)."""
        self._s = session

    def append(self, session_id: UUID, role: str, content: str) -> ChatMessage:
        """Stage one message (caller commits)."""
        row = ChatMessage(session_id=session_id, role=role, content=content)
        self._s.add(row)
        self._s.flush()
        return row

    def list_for(self, session_id: UUID) -> list[ChatMessage]:
        """The session's messages oldest-first."""
        return list(
            self._s.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.asc())
            )
        )
