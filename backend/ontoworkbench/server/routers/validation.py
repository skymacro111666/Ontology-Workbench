"""SHACL shapes storage + run endpoint + full-result export.

spec 2026-09-08 §2.1/§2.2 + 2026-09-14 export (B·缓存上次报告).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.parsing import ParseError, parse_store
from ontoworkbench.core.validation import (
    PRESETS,
    REPORT_CACHE,
    EngineFailure,
    PyrudofEngine,
    ReportEntry,
    ValidationTimeout,
    af_terms_in,
    normalize_report,
    report_to_csv,
    run_validated,
)
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import OntologyRepository, ValidationShapesRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/v1/ontologies", tags=["validation"])


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ShapesIn(CamelModel):
    """PUT body: the full shapes graph text."""

    source: str


def _owned_oid(user: User, session: Session, ontology_id: str) -> UUID:
    """Parse and ownership-check the oid (404 for foreign/invalid)."""
    try:
        oid = UUID(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    if not OntologyRepository(session).get_owned(user.id, oid):
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return oid


def _shapes_payload(session: Session, oid: UUID, af_warnings: list[str] | None = None) -> dict:
    """The GET/PUT response body: saved source + bundled presets."""
    row = ValidationShapesRepository(session).get(oid)
    out: dict[str, object] = {
        "source": row.source if row else None,
        "updatedAt": row.updated_at.isoformat() if row else None,
        "presets": [p.model_dump() for p in PRESETS],
    }
    if af_warnings is not None:
        out["afWarnings"] = af_warnings
    return out


def _parse_or_422(source: str) -> list[str]:
    """Turtle 预校验;返回 AF 命中词(合法才有意义)."""
    try:
        store, _ = parse_store(source.encode("utf-8"), "turtle")
    except ParseError as exc:
        raise ApiError(ErrorCode.SHAPES_INVALID, "Shapes are not valid Turtle", str(exc)) from None
    return af_terms_in(store)


@router.get("/{ontology_id}/validation/shapes")
def get_shapes(
    ontology_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Read the ontology's saved shapes (none yet: nulls) + the presets."""
    oid = _owned_oid(user, session, ontology_id)
    return respond(_shapes_payload(session, oid))


@router.put("/{ontology_id}/validation/shapes")
def put_shapes(
    ontology_id: str,
    body: ShapesIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Validate then save the shapes; AF-term hits ride back as warnings."""
    oid = _owned_oid(user, session, ontology_id)
    af = _parse_or_422(body.source)
    ValidationShapesRepository(session).upsert(oid, body.source)
    return respond(_shapes_payload(session, oid, af_warnings=af))


class RunIn(CamelModel):
    """POST body: optional inline shapes shadowing the saved source."""

    source: str | None = None
    # M2 忽略已废弃: default false = deprecated-focus results are dropped
    # (mirrors browse's includeDeprecated convention).
    include_deprecated: bool = False


class ExportIn(RunIn):
    """POST /validation/export body: run's knobs + the file format."""

    format: Literal["csv", "json"] = "csv"


def _shapes_hash(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _run_engine(request: Request, row, source: str) -> tuple[str, str, float]:
    """Fresh engine run with metrics + error mapping; caches the raw report.

    Returns (turtle, engine_name, elapsed_ms). The cache entry keys on
    revision + shapes hash so a later export can skip the re-run.
    """
    from ontoworkbench.observability.metrics import ow_validate_seconds

    engine = PyrudofEngine()
    with ow_validate_seconds.labels(engine.name).time():
        try:
            turtle, elapsed_ms = run_validated(
                engine,
                row.storage_path,
                source,
                row.format,
                request.app.state.settings.validate_timeout_s,
            )
        except ValidationTimeout as exc:
            raise ApiError(
                ErrorCode.VALIDATION_TIMEOUT,
                "Validation timed out",
                f"超过 {request.app.state.settings.validate_timeout_s:.0f}s;"
                "可调大 OW_VALIDATE_TIMEOUT_S 后重试",
            ) from exc
        except EngineFailure as exc:
            raise ApiError(
                ErrorCode.VALIDATION_ENGINE, "Validation engine failed", str(exc)[:300]
            ) from exc
    REPORT_CACHE.put(
        row.id.hex,
        ReportEntry(
            revision=row.revision,
            file_hash=row.file_hash,
            shapes_hash=_shapes_hash(source),
            turtle=turtle,
            engine=engine.name,
            elapsed_ms=elapsed_ms,
        ),
    )
    return turtle, engine.name, elapsed_ms


@router.post("/{ontology_id}/validation/run")
def run_validation(
    ontology_id: str,
    body: RunIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Read-only SHACL run against the on-disk file (spec §2.2).

    The engine reads the stored ontology directly (no store pool, no
    revision bump); elapsedMs is the engine-side measure from run_validated.
    """
    from ontoworkbench.observability.metrics import ow_validate_runs_total
    from ontoworkbench.server.routers.browse import _camel, _owned

    row, ix = _owned(request, user, ontology_id, session)
    stored = ValidationShapesRepository(session).get(row.id)
    source = body.source if body.source is not None else (stored.source if stored else None)
    if not source or not source.strip():
        raise ApiError(
            ErrorCode.SHAPES_REQUIRED,
            "No shapes to validate against",
            "保存 shapes 或在请求中提供 source",
        )
    turtle, engine_name, elapsed_ms = _run_engine(request, row, source)
    report = normalize_report(
        turtle,
        ix.ir.prefixes,
        drop_focus_iris=(
            None
            if body.include_deprecated
            else {eid for eid, e in ix.ir.entities.items() if e.deprecated}
        ),
    )
    af = _parse_or_422(source)  # PUT 已校验过;run 的内联 source 也要提示
    ow_validate_runs_total.labels(str(report.conforms).lower()).inc()
    return respond(
        _camel(
            {
                **report.model_dump(),
                "engine": engine_name,
                "elapsedMs": round(elapsed_ms, 1),
                "afWarnings": af,
            }
        )
    )


@router.post("/{ontology_id}/validation/export")
def export_validation(
    ontology_id: str,
    body: ExportIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> Response:
    """Full-result file download (cap-less), bypassing the JSON envelope.

    Site-archive zip precedent. Cache hit on (revision, file_hash, shapes
    hash) skips the engine; misses/staleness re-run transparently. Filter
    and format are applied post-cache, so they never invalidate anything.
    """
    from ontoworkbench.observability.metrics import ow_validate_exports_total
    from ontoworkbench.server.routers.browse import _camel, _owned

    row, ix = _owned(request, user, ontology_id, session)
    stored = ValidationShapesRepository(session).get(row.id)
    source = body.source if body.source is not None else (stored.source if stored else None)
    if not source or not source.strip():
        raise ApiError(
            ErrorCode.SHAPES_REQUIRED,
            "No shapes to validate against",
            "保存 shapes 或在请求中提供 source",
        )

    entry = REPORT_CACHE.get(row.id.hex)
    if (
        entry
        and entry.revision == row.revision
        and entry.file_hash == row.file_hash
        and entry.shapes_hash == _shapes_hash(source)
    ):
        turtle, engine_name, elapsed_ms = entry.turtle, entry.engine, entry.elapsed_ms
    else:
        turtle, engine_name, elapsed_ms = _run_engine(request, row, source)

    report = normalize_report(
        turtle,
        ix.ir.prefixes,
        cap=None,  # 导出=全量,这正是本端点的存在理由
        drop_focus_iris=(
            None
            if body.include_deprecated
            else {eid for eid, e in ix.ir.entities.items() if e.deprecated}
        ),
    )
    ow_validate_exports_total.labels(body.format).inc()
    stem = Path(row.filename).stem
    if body.format == "csv":
        return Response(
            content=report_to_csv(report),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}-validation.csv"'},
        )
    payload = {
        **_camel(report.model_dump()),
        "engine": engine_name,
        "elapsedMs": round(elapsed_ms, 1),
    }
    return Response(
        content=json.dumps(payload, ensure_ascii=False),
        media_type="application/json; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{stem}-validation.json"'},
    )
