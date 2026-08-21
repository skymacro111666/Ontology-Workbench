"""Docs-site export endpoint: renders a stored ontology into static HTML."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.parsing import parse_graph
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology, User
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.exporter.site import default_out_dir, export_site
from ontoworkbench.observability.metrics import ow_parse_seconds
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/ontologies", tags=["export"])


class CamelModel(BaseModel):
    """Base model serializing snake_case fields as camelCase."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ExportOptions(CamelModel):
    """Request body: optional target dir (blank = default) and force flag."""

    out_dir: str | None = None
    force: bool = False


class ExportSiteResult(CamelModel):
    """Export response payload: where the site landed and how big it is."""

    output_dir: str
    page_count: int


def _owned(user: User, ontology_id: str, session: Session) -> Ontology:
    """Resolve an owned ontology; uniform 404 for unknown, foreign, malformed ids."""
    try:
        oid = UUID(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    row = OntologyRepository(session).get_owned(user.id, oid)
    if not row:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return row


@router.post("/{ontology_id}/export/site")
def export_ontology_site(
    ontology_id: str,
    options: ExportOptions,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Render the stored file into out_dir (default {data_dir}/exports/{id}-{ts}).

    Re-parses the stored bytes exactly like `ow import` (build_ir →
    build_indexes); a non-empty out_dir raises VALIDATION_ERROR unless force.
    """
    row = _owned(user, ontology_id, session)

    store: LocalUserDirStore = request.app.state.store
    data = store.read(Path(row.storage_path))
    with ow_parse_seconds.labels(row.format).time():
        graph = parse_graph(data, row.format)
    ir = build_ir(graph)
    indexes = build_indexes(ir)

    raw = (options.out_dir or "").strip()
    target = Path(raw) if raw else default_out_dir(request.app.state.settings.data_dir, row.id)
    result = export_site(ir, indexes, target, row.title or row.filename, force=options.force)
    payload = ExportSiteResult(
        output_dir=str(result.output_dir), page_count=result.page_count
    ).model_dump(by_alias=True)
    return respond(payload)
