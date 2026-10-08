"""DB connection profiles (spec §3): CRUD + connect test + engines list.

Passwords are Fernet-encrypted at rest (key derived from the JWT secret) and
never leave the backend: list payloads omit them entirely; reflection paths
decrypt in-request only. The connect test does SELECT 1 — nothing else.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy import text
from sqlalchemy.orm import Session

from ontoworkbench.core.db_engines import ENGINES, ConnValues, Dialect, installed
from ontoworkbench.core.errors import CoreError
from ontoworkbench.db.models import DbConnection, User
from ontoworkbench.db.repositories import DbConnectionRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.crypto import decrypt_str, encrypt_str, fernet_from_jwt_secret
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/v1/db-connections", tags=["db-connections"])

_audit = structlog.get_logger("ow.audit")


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ConnectionIn(CamelModel):
    """Create body: a full profile (password included, encrypted before storage)."""

    name: str = Field(min_length=1, max_length=64)
    db_type: str = Field(min_length=1, max_length=16)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=255)


class ConnectionUpdateIn(CamelModel):
    """PUT body: partial; password omitted/empty keeps the stored ciphertext."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=255)


class TestIn(CamelModel):
    """Connect test: by saved id, or by raw values (nothing persisted)."""

    connection_id: uuid.UUID | None = None
    db_type: str | None = Field(default=None, min_length=1, max_length=16)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, min_length=1, max_length=255)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=255)


def _dialect(db_type: str | None) -> Dialect:
    """Resolve the registry dialect or 422."""
    d = ENGINES.get(db_type or "")
    if d is None:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"unknown dbType: {db_type}")
    return d


def _payload(row: DbConnection) -> dict:
    """A list/detail row without any password material."""
    return {
        "id": str(row.id),
        "name": row.name,
        "dbType": row.db_type,
        "host": row.host,
        "port": row.port,
        "database": row.database_name,
        "username": row.username,
        "hasPassword": bool(row.password_cipher),
        "createdAt": row.created_at.isoformat(),
    }


def _values_from_body(body: ConnectionIn | TestIn, dialect: Dialect) -> ConnValues:
    """Body fields → ConnValues (SQLite: database carries the path)."""
    return ConnValues(
        host=body.host,
        port=body.port,
        database=body.database or "",
        username=body.username,
        password=body.password,
    )


def _fernet(request: Request):
    """Fernet keyed off this app's JWT secret."""
    return fernet_from_jwt_secret(request.app.state.settings.jwt_secret)


def _check_connect(dialect: Dialect, values: ConnValues) -> dict:
    """SELECT 1 against the target; ok=False (OK envelope) on failure."""
    from sqlalchemy import create_engine

    try:
        engine = create_engine(dialect.url(values), connect_args=dict(dialect.connect_args))
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        finally:
            engine.dispose()
    except Exception as e:  # noqa: BLE001 - the test endpoint reports any failure
        return {"ok": False, "message": str(e)[:300]}
    return {"ok": True}


@router.get("")
def list_connections(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """The user's saved profiles (newest first, no password material)."""
    rows = DbConnectionRepository(session).list_by_user(user.id)
    return respond([_payload(r) for r in rows])


@router.post("", status_code=201)
def create_connection(
    body: ConnectionIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Save a profile; the password lands as Fernet ciphertext."""
    dialect = _dialect(body.db_type)
    repo = DbConnectionRepository(session)
    if any(r.name == body.name for r in repo.list_by_user(user.id)):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "connection name already exists")
    row = repo.create(
        user_id=user.id,
        name=body.name,
        db_type=dialect.db_type,
        host=body.host,
        port=body.port,
        database_name=body.database,
        username=body.username,
        password_cipher=encrypt_str(_fernet(request), body.password or ""),
    )
    session.commit()
    _audit.info(
        "db_connection.create", name=body.name, db_type=dialect.db_type, user_id=str(user.id)
    )
    return respond(_payload(row))


@router.put("/{connection_id}")
def update_connection(
    connection_id: uuid.UUID,
    body: ConnectionUpdateIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Partially update; password omitted/empty keeps the stored ciphertext."""
    repo = DbConnectionRepository(session)
    row = repo.get_owned(user.id, connection_id)
    if row is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No such connection")
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name
    if body.host is not None:
        fields["host"] = body.host
    if body.port is not None:
        fields["port"] = body.port
    if body.database is not None:
        fields["database_name"] = body.database
    if body.username is not None:
        fields["username"] = body.username
    if body.password:
        fields["password_cipher"] = encrypt_str(_fernet(request), body.password)
    repo.update(row, **fields)
    session.commit()
    _audit.info("db_connection.update", connection_id=str(connection_id), user_id=str(user.id))
    return respond(_payload(row))


@router.delete("/{connection_id}")
def delete_connection(
    connection_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Hard-delete an owned profile."""
    if not DbConnectionRepository(session).delete(user.id, connection_id):
        raise ApiError(ErrorCode.NOT_FOUND, "No such connection")
    session.commit()
    _audit.info("db_connection.delete", connection_id=str(connection_id), user_id=str(user.id))
    return respond()


@router.get("/engines")
def list_engines(user: User = Depends(get_current_user)) -> dict:
    """Registry listing with installed flags for the wizard's dropdown."""
    return respond(
        [
            {"dbType": d.db_type, "label": d.label, "installed": installed(d)}
            for d in ENGINES.values()
        ]
    )


@router.post("/test")
def test_connection(
    body: TestIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """SELECT 1 by saved id (decrypt in-request) or by raw values."""
    if body.connection_id is not None:
        row = DbConnectionRepository(session).get_owned(user.id, body.connection_id)
        if row is None:
            raise ApiError(ErrorCode.NOT_FOUND, "No such connection")
        dialect = ENGINES.get(row.db_type)
        if dialect is None:
            raise ApiError(ErrorCode.VALIDATION_ERROR, f"unknown dbType: {row.db_type}")
        values = ConnValues(
            host=row.host,
            port=row.port,
            database=row.database_name,
            username=row.username,
            password=decrypt_str(_fernet(request), row.password_cipher)
            if row.password_cipher
            else None,
        )
    else:
        dialect = _dialect(body.db_type)
        if not body.database:
            raise ApiError(ErrorCode.VALIDATION_ERROR, "database is required")
        values = _values_from_body(body, dialect)
    try:
        return respond(_check_connect(dialect, values))
    except CoreError as e:
        raise ApiError(ErrorCode(str(e.code)), e.message, e.hint) from e
