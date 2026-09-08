"""SHACL shapes storage (spec 2026-09-08 §2.1) + run endpoint (Task 4)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.parsing import ParseError, parse_store
from ontoworkbench.core.validation import PRESETS, af_terms_in
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import OntologyRepository, ValidationShapesRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond

router = APIRouter(prefix="/api/ontologies", tags=["validation"])


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
