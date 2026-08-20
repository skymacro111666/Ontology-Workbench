"""SQLAlchemy ORM models (SQLite/PG compatible)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, Uuid

DateTimeTZ = DateTime(timezone=True)
StatsJSON = JSON().with_variant(JSONB(), "postgresql")

# Deterministic constraint names keep autogenerate migrations stable across
# backends (and are required for SQLite batch ALTERs in later migrations).
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Declarative base with a deterministic naming convention."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class User(Base):
    """A workspace owner; Phase 1 has exactly one (admin)."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTimeTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTimeTZ, server_default=func.now(), onupdate=_now
    )
    ontologies: Mapped[list[Ontology]] = relationship(back_populates="owner", cascade="all, delete")


class Ontology(Base):
    """Registry row: metadata about one stored ontology file."""

    __tablename__ = "ontologies"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "filename", name="uq_ontologies_owner_filename"),
        Index("ix_ontologies_owner", "owner_user_id"),
        Index("ix_ontologies_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_user_id: Mapped[UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(String(256))
    filename: Mapped[str] = mapped_column(String(256))
    storage_path: Mapped[str] = mapped_column(String(512))
    format: Mapped[str] = mapped_column(String(16))
    class_count: Mapped[int] = mapped_column(Integer, default=0)
    property_count: Mapped[int] = mapped_column(Integer, default=0)
    axiom_count: Mapped[int] = mapped_column(Integer, default=0)
    stats_json: Mapped[dict[str, Any] | None] = mapped_column(StatsJSON)
    file_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    file_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTimeTZ, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTimeTZ, server_default=func.now(), onupdate=_now
    )
    owner: Mapped[User] = relationship(back_populates="ontologies")
