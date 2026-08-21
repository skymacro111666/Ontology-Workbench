"""Ontology management endpoints: upload/list/delete/samples."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from rdflib import DCTERMS, OWL, RDF
from sqlalchemy.orm import Session

from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.parsing import parse_graph, sniff_format
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.observability.metrics import ow_parse_seconds, ow_uploads_total
from ontoworkbench.server.cache import OntologyCache
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api", tags=["ontologies"])

MAX_UPLOAD = 150 * 1024 * 1024


class CamelModel(BaseModel):
    """Base model serializing snake_case fields as camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class OntologyMeta(CamelModel):
    """Upload response: full metadata of one ontology."""

    id: str
    title: str
    filename: str
    format: str
    class_count: int
    property_count: int
    axiom_count: int
    file_size_bytes: int
    file_hash: str
    prefixes: dict[str, str] = Field(default_factory=dict)
    created_at: str


class OntologySummary(CamelModel):
    """List item: lighter metadata."""

    id: str
    title: str
    filename: str
    format: str
    class_count: int
    property_count: int
    axiom_count: int
    file_size_bytes: int
    created_at: str


def _title_of(graph, filename: str) -> str:
    """dc:title of the owl:Ontology node, else the filename stem."""
    for ont in graph.subjects(RDF.type, OWL.Ontology):
        title = graph.value(ont, DCTERMS.title)
        if title:
            return str(title)
    return filename.rsplit(".", 1)[0]


def _meta(row: Ontology) -> dict[str, Any]:
    """Assemble the camelCase OntologyMeta payload for a row."""
    prefixes = (row.stats_json or {}).get("prefixes", {})
    return OntologyMeta(
        id=str(row.id),
        title=row.title or row.filename,
        filename=row.filename,
        format=row.format,
        class_count=row.class_count,
        property_count=row.property_count,
        axiom_count=row.axiom_count,
        file_size_bytes=row.file_size_bytes,
        file_hash=row.file_hash,
        prefixes=prefixes,
        created_at=row.created_at.isoformat(),
    ).model_dump(by_alias=True)


def _summary(row: Ontology) -> dict[str, Any]:
    """Assemble the camelCase OntologySummary payload for a row."""
    return OntologySummary(
        id=str(row.id),
        title=row.title or row.filename,
        filename=row.filename,
        format=row.format,
        class_count=row.class_count,
        property_count=row.property_count,
        axiom_count=row.axiom_count,
        file_size_bytes=row.file_size_bytes,
        created_at=row.created_at.isoformat(),
    ).model_dump(by_alias=True)


def _import_bytes(
    request: Request,
    user: User,
    session: Session,
    filename: str,
    data: bytes,
) -> Ontology:
    """Shared import path for uploads and samples: parse, store, register."""
    repos = OntologyRepository(session)
    store: LocalUserDirStore = request.app.state.store
    existing = repos.find_by_filename(user.id, filename)
    if existing:
        raise ApiError(
            ErrorCode.DUPLICATE_FILENAME,
            f"'{filename}' already exists",
            "Rename the file or delete the existing ontology first.",
        )
    fmt = sniff_format(filename, data[:2048])
    with ow_parse_seconds.labels(fmt).time():
        graph = parse_graph(data, fmt)
    ir = build_ir(graph)

    oid = uuid4()
    path = store.save(user.id, oid, filename, data)
    row = repos.create(
        user.id,
        id=oid,
        title=_title_of(graph, filename),
        filename=filename,
        storage_path=str(path),
        format=fmt,
        class_count=ir.counts.class_count,
        property_count=ir.counts.property_count,
        axiom_count=ir.counts.axiom_count,
        stats_json={"prefixes": ir.prefixes},
        file_size_bytes=len(data),
        file_hash=LocalUserDirStore.file_hash(data),
    )
    cache: OntologyCache = request.app.state.cache
    cache.indexes_for(row, lambda r: build_indexes(ir))
    ow_uploads_total.labels("ok").inc()
    return row


@router.post("/ontologies", status_code=201)
async def upload_ontology(
    request: Request,
    file: UploadFile,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Multipart upload: sniff, parse, store, register; 150MB cap."""
    # Reject oversized bodies before buffering them (brief: check before read).
    if file.size is not None and file.size > MAX_UPLOAD:
        ow_uploads_total.labels("too_large").inc()
        raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
    data = await file.read()
    if len(data) > MAX_UPLOAD:  # belt: chunked encodings may report size=None
        ow_uploads_total.labels("too_large").inc()
        raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
    filename = file.filename or "upload"
    row = _import_bytes(request, user, session, filename, data)
    return respond(_meta(row))


@router.get("/ontologies")
def list_ontologies(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """All ontologies of the current user, newest first."""
    rows = OntologyRepository(session).list_by_owner(user.id)
    return respond({"items": [_summary(r) for r in rows], "total": len(rows)})


@router.get("/ontologies/{ontology_id}/meta")
def get_meta(
    ontology_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """One ontology's metadata (counts + prefixes); uniform 404 otherwise."""
    try:
        oid = _to_uuid(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid) if oid else None
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return respond(_meta(row))


@router.delete("/ontologies/{ontology_id}")
def delete_ontology(
    ontology_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Delete record + files; unknown or foreign ids are 404."""
    repos = OntologyRepository(session)
    try:
        oid = _to_uuid(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = repos.get_owned(user.id, oid) if oid else None
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    store: LocalUserDirStore = request.app.state.store
    store.delete(user.id, UUID(str(row.id)))
    repos.delete(row.id)
    cache: OntologyCache = request.app.state.cache
    cache.drop(str(row.id))
    return respond(None)


@router.post("/samples/{name}", status_code=201)
def import_sample(
    name: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Import a bundled sample; idempotent per filename."""
    store: LocalUserDirStore = request.app.state.store
    sample = store.sample_path(name)
    data = store.read(sample)
    existing = OntologyRepository(session).find_by_filename(user.id, sample.name)
    if existing:
        return respond(_meta(existing))
    row = _import_bytes(request, user, session, sample.name, data)
    return respond(_meta(row))


def _to_uuid(value: str) -> UUID:
    """Parse a path parameter as UUID; ValueError when malformed."""
    return UUID(value)
