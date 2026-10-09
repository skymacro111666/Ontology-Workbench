"""Drafting endpoints (spec §5): schema reflect, generate job, agent import.

The wizard's three steps map to three POSTs: reflect a database (by saved
connection or raw values), generate decisions as a polled background job,
then import the user-checked subset as an agent-sourced ontology. Import
reuses the shared _import_bytes path so the Registry journal records the
agent origin.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.ai.base import ModelProvider
from ontoworkbench.core.db_engines import ENGINES, ConnValues, Dialect
from ontoworkbench.core.drafting.guard import run_guardrails
from ontoworkbench.core.drafting.merge import apply_rejections, merge_decisions, render_ttl
from ontoworkbench.core.drafting.models import DecisionSet, SchemaModel
from ontoworkbench.core.drafting.pipeline import _prefix_for, generate_draft
from ontoworkbench.core.drafting.reflect import reflect_schema
from ontoworkbench.core.errors import CoreError
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import DbConnectionRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.crypto import decrypt_str, fernet_from_jwt_secret
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.ai_settings import get_ai_provider
from ontoworkbench.server.routers.browse import _camel
from ontoworkbench.server.routers.ontologies import _import_bytes

router = APIRouter(prefix="/api/v1/ontologies/drafting", tags=["drafting"])


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SchemaIn(CamelModel):
    """Reflect by saved connectionId or by raw values (sqlite: database=path)."""

    connection_id: uuid.UUID | None = None
    db_type: str | None = Field(default=None, min_length=1, max_length=16)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=128)
    password: str | None = Field(default=None, max_length=255)


class GenerateIn(CamelModel):
    """Generate body: the (possibly subset) schema plus wizard options."""

    schema_: SchemaModel = Field(alias="schema")
    namespace: str | None = Field(default=None, max_length=512)
    label_language: str = Field(default="zh", pattern="^(zh|en)$")


class ImportIn(CamelModel):
    """Import body: the merged decisions the user saw + unchecked class names."""

    schema_: SchemaModel = Field(alias="schema")
    decisions: DecisionSet
    rejected_class_names: list[str] = Field(default_factory=list)
    namespace: str = Field(min_length=1, max_length=512)
    filename: str | None = Field(default=None, max_length=255)
    label_language: str = Field(default="zh", pattern="^(zh|en)$")


def _dialect(db_type: str | None) -> Dialect:
    """Resolve the registry dialect or 422 (same contract as db-connections)."""
    d = ENGINES.get(db_type or "")
    if d is None:
        raise ApiError(ErrorCode.VALIDATION_ERROR, f"unknown dbType: {db_type}")
    return d


def _resolve_values(
    body: SchemaIn, request: Request, user: User, session: Session
) -> tuple[Dialect, ConnValues]:
    """ConnectionId → decrypt in-request; else raw body values."""
    if body.connection_id is not None:
        row = DbConnectionRepository(session).get_owned(user.id, body.connection_id)
        if row is None:
            raise ApiError(ErrorCode.NOT_FOUND, "No such connection")
        dialect = _dialect(row.db_type)
        return dialect, ConnValues(
            host=row.host,
            port=row.port,
            database=row.database_name,
            username=row.username,
            password=decrypt_str(_fernet(request), row.password_cipher)
            if row.password_cipher
            else None,
        )
    dialect = _dialect(body.db_type)
    if not body.database:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "database is required")
    return dialect, ConnValues(
        host=body.host,
        port=body.port,
        database=body.database,
        username=body.username,
        password=body.password,
    )


def _fernet(request: Request):
    """Fernet keyed off this app's JWT secret."""
    return fernet_from_jwt_secret(request.app.state.settings.jwt_secret)


@router.post("/schema")
def reflect_endpoint(
    body: SchemaIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Reflect the target database: tables, columns, FKs (read-only inspector)."""
    dialect, values = _resolve_values(body, request, user, session)
    try:
        schema = reflect_schema(values, dialect)
    except CoreError as e:
        raise ApiError(ErrorCode(str(e.code)), e.message, e.hint) from e
    return respond({"schema": schema.model_dump(by_alias=True), "tableCount": len(schema.tables)})


@router.post("/generate", status_code=202)
def generate_endpoint(
    body: GenerateIn,
    request: Request,
    provider: ModelProvider = Depends(get_ai_provider),
    user: User = Depends(get_current_user),
) -> dict:
    """Kick off the drafting pipeline as a background job; jobId immediately."""
    namespace = body.namespace or f"https://local/{body.schema_.database_name}#"

    def factory(progress):
        async def run() -> dict:
            r = await generate_draft(
                provider,
                body.schema_,
                namespace=namespace,
                label_language=body.label_language,
                progress=progress,
            )
            return {
                "decisions": r.decisions.model_dump(by_alias=True),
                "ttl": r.ttl.decode("utf-8"),
                "lintFindings": [_camel(f) for f in r.lint_findings],
                "stats": r.stats,
            }

        return run()

    job_id = request.app.state.draft_jobs.submit(factory)
    return respond({"jobId": job_id})


@router.get("/jobs/{job_id}")
def job_endpoint(job_id: str, request: Request, user: User = Depends(get_current_user)) -> dict:
    """Poll one generate job: batch progress now, result/code/message at the end."""
    job = request.app.state.draft_jobs.get(job_id)
    if job is None:
        raise ApiError(ErrorCode.NOT_FOUND, "No such job")
    payload: dict = {
        "status": job["status"],
        "batch": job["batch"],
        "batchCount": job["batchCount"],
    }
    if job["status"] == "done":
        payload["result"] = job["result"]
    elif job["status"] == "failed":
        payload["code"] = job["code"]
        payload["message"] = job["message"]
    return respond(payload)


@router.post("/import", status_code=201)
def import_endpoint(
    body: ImportIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Merge the kept decisions, cascade rejections, import as agent-sourced."""
    draft = merge_decisions([body.decisions], body.schema_)
    apply_rejections(draft, set(body.rejected_class_names))
    ttl = render_ttl(
        draft,
        namespace=body.namespace,
        prefix=_prefix_for(body.schema_.database_name),
        title=body.schema_.database_name,
        label_language=body.label_language,
    )
    findings = [_camel(f) for f in run_guardrails(ttl)]
    row = _import_bytes(
        request,
        user,
        session,
        body.filename or f"{body.schema_.database_name}-draft.ttl",
        ttl,
        source="agent",
        journal_origin="agent",
    )
    return respond({"ontologyId": str(row.id), "title": row.title, "lintFindings": findings})
