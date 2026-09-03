"""Ontology management endpoints: upload/list/delete/samples."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pyoxigraph import DefaultGraph, NamedNode, Store
from pyoxigraph import Literal as OxLiteral
from rdflib import DCTERMS, OWL, RDF
from sqlalchemy.orm import Session

from ontoworkbench.core import terms
from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.ir_cache import write_ir_cache
from ontoworkbench.core.parsing import sniff_format, timed_parse_store
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import LayoutRepository, OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.observability.metrics import ow_build_seconds, ow_parse_seconds, ow_uploads_total
from ontoworkbench.observability.middleware import request_id_ctx
from ontoworkbench.server.cache import OntologyCache
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api", tags=["ontologies"])

MAX_UPLOAD = 150 * 1024 * 1024

_imports_log = structlog.get_logger("ow.imports")
_audit = structlog.get_logger("ow.audit")


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
    instance_count: int
    file_size_bytes: int
    file_hash: str
    source: str = "upload"
    prefixes: dict[str, str] = Field(default_factory=dict)
    parse_ms: float | None = None
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
    instance_count: int
    file_size_bytes: int
    source: str = "upload"
    created_at: str


class SourceUpdate(CamelModel):
    """PUT /source body: full new text + the file hash it was based on."""

    content: str
    base_file_hash: str


class BlankCreate(CamelModel):
    """POST /ontologies/blank body: a human name + optional namespace."""

    name: str = Field(min_length=1, max_length=128)
    namespace: str | None = Field(default=None, max_length=512)


def _slugify(text: str) -> str:
    """ASCII filename slug; non-ASCII names fall back to a stable default."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "ontology"


def blank_skeleton(name: str, namespace: str, prefix: str) -> bytes:
    """Starter document for a blank create.

    Ontology header + label + one prefix + one class and one property,
    so a brand-new ontology opens onto a living canvas.
    """
    esc = name.replace("\\", "\\\\").replace('"', '\\"')
    onto_iri = namespace.rstrip("#/")
    return (
        "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        f"@prefix {prefix}: <{namespace}> .\n"
        "\n"
        f"<{onto_iri}> a owl:Ontology ;\n"
        f'    rdfs:label "{esc}" ;\n'
        f'    dcterms:title "{esc}" .\n'
        "\n"
        f"{prefix}:Example a owl:Class ;\n"
        '    rdfs:label "Example" .\n'
        "\n"
        f"{prefix}:relatedTo a owl:ObjectProperty ;\n"
        '    rdfs:label "related to" .\n'
    ).encode()


def title_of(graph, filename: str) -> str:
    """dc:title of the owl:Ontology node, else the filename stem."""
    for ont in graph.subjects(RDF.type, OWL.Ontology):
        title = graph.value(ont, DCTERMS.title)
        if title:
            return str(title)
    return filename.rsplit(".", 1)[0]


def title_of_store(store: Store, filename: str) -> str:
    """dc:title of the owl:Ontology node, else the filename stem (ox path).

    Same contract as title_of above — kept separate because the edit paths
    (entities.py) still walk an rdflib graph. Subjects are sorted so the
    pick under multiple owl:Ontology declarations is deterministic,
    matching build_ir_store's ontology_iri choice.
    """
    subjects = sorted(
        q.subject.value
        for q in store.quads_for_pattern(None, terms.RDF_TYPE, terms.OWL_ONTOLOGY, DefaultGraph())
        if isinstance(q.subject, NamedNode)
    )
    for ont in subjects:
        for q in store.quads_for_pattern(NamedNode(ont), terms.DCTERMS_TITLE, None, DefaultGraph()):
            if isinstance(q.object, OxLiteral):
                return q.object.value
    return filename.rsplit(".", 1)[0]


def meta_of(row: Ontology) -> dict[str, Any]:
    """Assemble the camelCase OntologyMeta payload for a row."""
    prefixes = (row.stats_json or {}).get("prefixes", {})
    parse_ms = (row.stats_json or {}).get("parse_ms")
    return OntologyMeta(
        id=str(row.id),
        title=row.title or row.filename,
        filename=row.filename,
        format=row.format,
        class_count=row.class_count,
        property_count=row.property_count,
        axiom_count=row.axiom_count,
        instance_count=row.instance_count,
        file_size_bytes=row.file_size_bytes,
        file_hash=row.file_hash,
        source=row.source,
        prefixes=prefixes,
        parse_ms=parse_ms,
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
        instance_count=row.instance_count,
        file_size_bytes=row.file_size_bytes,
        source=row.source,
        created_at=row.created_at.isoformat(),
    ).model_dump(by_alias=True)


def _import_bytes(
    request: Request,
    user: User,
    session: Session,
    filename: str,
    data: bytes,
    read_ms: float | None = None,
    source: str = "upload",
) -> Ontology:
    """Shared import path for uploads and samples: parse, store, register.

    Both outcomes leave an ops trace on ow.imports: success carries file,
    staged timings (read/parse/ir/store/db/index, spec observability §3) and
    counts; failure carries the rejecting code. The HTTP error handler still
    logs the envelope — these events carry the file context that one lacks,
    plus request_id so the two lines join without timestamp guessing.
    """
    started = time.perf_counter()
    try:
        repos = OntologyRepository(session)
        store: LocalUserDirStore = request.app.state.store
        t_dup = time.perf_counter()
        existing = repos.find_by_filename(user.id, filename)
        dup_ms = time.perf_counter() - t_dup
        if existing:
            raise ApiError(
                ErrorCode.DUPLICATE_FILENAME,
                f"'{filename}' already exists",
                "Rename the file or delete the existing ontology first.",
            )
        fmt = sniff_format(filename, data[:2048])
        t_parse = time.perf_counter()
        with ow_parse_seconds.labels(fmt).time():
            ox_store, prefixes, parse_ms = timed_parse_store(data, fmt)
        parse_ms = round((time.perf_counter() - t_parse) * 1000, 1)
        t_ir = time.perf_counter()
        with ow_build_seconds.time():
            ir = build_ir_store(ox_store, prefixes)
        ir_ms = round((time.perf_counter() - t_ir) * 1000, 1)

        oid = uuid4()
        t_store = time.perf_counter()
        path = store.save(user.id, oid, filename, data)
        store_ms = round((time.perf_counter() - t_store) * 1000, 1)
        t_create = time.perf_counter()
        row = repos.create(
            user.id,
            id=oid,
            title=title_of_store(ox_store, filename),
            filename=filename,
            storage_path=str(path),
            format=fmt,
            source=source,
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            axiom_count=ir.counts.axiom_count,
            instance_count=ir.counts.individual_count,
            stats_json={
                "prefixes": ir.prefixes,
                "parse_ms": parse_ms,
                "ir_ms": ir_ms,
            },
            file_size_bytes=len(data),
            file_hash=LocalUserDirStore.file_hash(data),
        )
        # db_ms sums the two DB round-trips (dup-check + insert); parse and
        # IR run between them and must not bleed into this stage.
        db_ms = round((dup_ms + (time.perf_counter() - t_create)) * 1000, 1)
        t_index = time.perf_counter()
        cache: OntologyCache = request.app.state.cache
        cache.indexes_for(row, lambda r: build_indexes(ir))
        # The disk cache must move with the file: the next cold start would
        # otherwise re-pay the full parse for this ontology.
        write_ir_cache(Path(row.storage_path), ir, row.file_hash)
        index_ms = round((time.perf_counter() - t_index) * 1000, 1)
    except Exception as exc:
        _imports_log.error(
            "ontology.import_failed",
            source="http",
            filename=filename,
            size_bytes=len(data),
            error_code=str(getattr(exc, "code", type(exc).__name__)),
            error_type=type(exc).__name__,
            user_id=str(user.id),
            request_id=request_id_ctx.get(),
        )
        raise
    _imports_log.info(
        "ontology.import",
        source="http",
        filename=filename,
        format=fmt,
        size_bytes=len(data),
        read_ms=round(read_ms, 1) if read_ms is not None else None,
        parse_ms=parse_ms,
        ir_ms=ir_ms,
        store_ms=store_ms,
        db_ms=db_ms,
        index_ms=index_ms,
        class_count=ir.counts.class_count,
        property_count=ir.counts.property_count,
        instance_count=ir.counts.individual_count,
        axiom_count=ir.counts.axiom_count,
        ontology_id=str(oid),
        user_id=str(user.id),
        request_id=request_id_ctx.get(),
        total_ms=round((time.perf_counter() - started) * 1000, 1),
    )
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
    t_read = time.perf_counter()
    data = await file.read()
    read_ms = (time.perf_counter() - t_read) * 1000
    if len(data) > MAX_UPLOAD:  # belt: chunked encodings may report size=None
        ow_uploads_total.labels("too_large").inc()
        raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
    filename = file.filename or "upload"
    row = _import_bytes(request, user, session, filename, data, read_ms=read_ms)
    return respond(meta_of(row))


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
    return respond(meta_of(row))


@router.put("/ontologies/{ontology_id}/source")
def replace_source(
    ontology_id: str,
    body: SourceUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Parse-validate, then atomically replace the stored source file.

    Optimistic lock: base_file_hash must match the row, else 409 with the
    file untouched. Parse failures keep the file untouched (400 envelope
    via the ParseError handler). Write order is file-then-row: a row-update
    failure self-heals in the cache (mtime moved), the reverse would pin
    stale indexes.
    """
    try:
        oid = _to_uuid(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid) if oid else None
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")

    data = body.content.encode("utf-8")
    if len(data) > MAX_UPLOAD:
        ow_uploads_total.labels("too_large").inc()
        raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
    if body.base_file_hash != row.file_hash:
        raise ApiError(
            ErrorCode.EDIT_CONFLICT,
            "The file changed since it was loaded",
            "Reload the source and reapply your edits on top.",
        )
    with ow_parse_seconds.labels(row.format).time():
        ox_store, prefixes, parse_ms = timed_parse_store(data, row.format)
    with ow_build_seconds.time():
        ir = build_ir_store(ox_store, prefixes)

    store: LocalUserDirStore = request.app.state.store
    store.save(user.id, UUID(str(row.id)), row.filename, data)
    repos = OntologyRepository(session)
    row = (
        repos.update(
            row.id,
            title=title_of_store(ox_store, row.filename),
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            axiom_count=ir.counts.axiom_count,
            instance_count=ir.counts.individual_count,
            stats_json={"prefixes": ir.prefixes, "parse_ms": round(parse_ms, 1)},
            file_size_bytes=len(data),
            file_hash=LocalUserDirStore.file_hash(data),
        )
        or row
    )  # update() of an owned row cannot miss; keep mypy happy
    cache: OntologyCache = request.app.state.cache
    cache.indexes_for(row, lambda r: build_indexes(ir))
    write_ir_cache(Path(row.storage_path), ir, row.file_hash)
    return respond(meta_of(row))


@router.delete("/ontologies/{ontology_id}")
def delete_ontology(
    ontology_id: str,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Delete record + files; unknown or foreign ids are 404.

    Physical cleanup runs in explicit stages (store → db → layout → cache);
    each stage failure emits ontology.delete_failed naming the broken step,
    success emits ontology.delete with the full audit context (spec §4).
    """
    repos = OntologyRepository(session)
    try:
        oid = _to_uuid(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = repos.get_owned(user.id, oid) if oid else None
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    store: LocalUserDirStore = request.app.state.store
    cache: OntologyCache = request.app.state.cache
    layouts = LayoutRepository(session)
    started = time.perf_counter()

    def _audit_failed(stage: str, exc: Exception) -> None:
        _audit.error(
            "ontology.delete_failed",
            request_id=request_id_ctx.get(),
            user_id=str(user.id),
            ontology_id=str(row.id),
            filename=row.filename,
            failed_stage=stage,
            error_type=type(exc).__name__,
        )

    try:
        store.delete(user.id, UUID(str(row.id)))
    except Exception as exc:
        _audit_failed("store", exc)
        raise
    try:
        repos.delete(row.id)
    except Exception as exc:
        _audit_failed("db", exc)
        raise
    try:
        layout_existed = layouts.get(UUID(str(row.id))) is not None
        layouts.delete(UUID(str(row.id)))
    except Exception as exc:
        _audit_failed("layout", exc)
        raise
    try:
        cache_evicted = cache.drop(str(row.id))
    except Exception as exc:
        _audit_failed("cache", exc)
        raise
    _audit.info(
        "ontology.delete",
        request_id=request_id_ctx.get(),
        user_id=str(user.id),
        ontology_id=str(row.id),
        filename=row.filename,
        size_bytes=row.file_size_bytes,
        layout_deleted=layout_existed,
        cache_evicted=cache_evicted,
        duration_ms=round((time.perf_counter() - started) * 1000, 1),
    )
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
        return respond(meta_of(existing))
    row = _import_bytes(request, user, session, sample.name, data, source="sample")
    return respond(meta_of(row))


@router.post("/ontologies/blank", status_code=201)
def create_blank_ontology(
    body: BlankCreate,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Mint a new ontology from a skeleton.

    Header + label + prefix + one class and one property
    (source=created, no 示例 badge).
    """
    name = body.name.strip()
    if not name:
        raise ApiError(ErrorCode.VALIDATION_ERROR, "Name cannot be blank")
    slug = _slugify(name)
    namespace = body.namespace.strip() if body.namespace else f"https://local/{slug}#"
    if any(ch.isspace() for ch in namespace):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "Namespace must not contain whitespace")
    prefix = f"o{slug}" if slug[0].isdigit() else slug
    data = blank_skeleton(name, namespace, prefix)
    row = _import_bytes(request, user, session, f"{slug}.ttl", data, source="created")
    return respond(meta_of(row))


def _to_uuid(value: str) -> UUID:
    """Parse a path parameter as UUID; ValueError when malformed."""
    return UUID(value)


class LayoutPosition(CamelModel):
    """One node position in canvas pixels."""

    x: float
    y: float


class LayoutUpdate(CamelModel):
    """Whole-map position overwrite; keys are entity IRIs (eids)."""

    positions: dict[str, LayoutPosition]


MAX_LAYOUT_NODES = 5000


def _owned(user: User, session: Session, ontology_id: str) -> Ontology:
    """Resolve an owned ontology row or raise the shared 404."""
    try:
        oid = _to_uuid(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid)
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return row


@router.get("/ontologies/{ontology_id}/layout")
def get_layout(
    ontology_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Saved canvas positions; empty map when never saved (not an error)."""
    row = _owned(user, session, ontology_id)
    saved = LayoutRepository(session).get(row.id)
    raw = saved.positions if saved else {}
    positions = {k: {"x": v["x"], "y": v["y"]} for k, v in (raw or {}).items()}
    return respond({"positions": positions})


@router.put("/ontologies/{ontology_id}/layout")
def put_layout(
    ontology_id: str,
    body: LayoutUpdate,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Overwrite the whole position map (last-write-wins, no file involved)."""
    row = _owned(user, session, ontology_id)
    if len(body.positions) > MAX_LAYOUT_NODES:
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Too many positions: {len(body.positions)} > {MAX_LAYOUT_NODES}",
        )
    LayoutRepository(session).upsert(
        row.id, {k: {"x": v.x, "y": v.y} for k, v in body.positions.items()}
    )
    return respond({"positions": {k: {"x": v.x, "y": v.y} for k, v in body.positions.items()}})


@router.delete("/ontologies/{ontology_id}/layout")
def delete_layout(
    ontology_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Reset to the automatic layout by dropping the saved positions."""
    row = _owned(user, session, ontology_id)
    LayoutRepository(session).delete(row.id)
    return respond(None)
