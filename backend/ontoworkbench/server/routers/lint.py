"""Lint configuration + manual runs (B3).

Config lives in DB per ontology; runs read the pooled Store (manual
trigger only, spec §0). A run concurrent with an in-flight edit may
observe that edit's not-yet-persisted changes (shared pooled Store).
"""

from __future__ import annotations

import time
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.lint import CustomRuleSpec
from ontoworkbench.core.lint import run as run_lint_engine
from ontoworkbench.db.models import User
from ontoworkbench.db.repositories import LintRuleRepository
from ontoworkbench.db.session import get_session
from ontoworkbench.server.cache import OntologyCache, load_store
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.browse import _camel, _owned

router = APIRouter(prefix="/api/ontologies", tags=["lint"])


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class CustomRuleIn(CamelModel):
    """A user-authored SPARQL rule."""

    name: str
    severity: str  # error | warning | info
    sparql: str
    enabled: bool = True


class LintConfigIn(CamelModel):
    """The whole lint config, PUT semantics."""

    disabled: list[str] = Field(default_factory=list)
    custom: list[CustomRuleIn] = Field(default_factory=list)


def _lint_owned(user: User, session: Session, ontology_id: str) -> UUID:
    """Parse and ownership-check the oid (404 for foreign/invalid)."""
    from ontoworkbench.db.repositories import OntologyRepository

    try:
        oid = UUID(ontology_id)
    except ValueError:
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology") from None
    if not OntologyRepository(session).get_owned(user.id, oid):
        raise ApiError(ErrorCode.NOT_FOUND, "No such ontology")
    return oid


def _config_payload(session: Session, oid: UUID) -> dict:
    """The GET/PUT response body: disabled ids + custom rule rows."""
    rows = LintRuleRepository(session).list_for(oid)
    return {
        "disabled": [r.key for r in rows if r.kind == "builtin"],
        "custom": [
            {
                "id": str(r.id),
                "name": r.name,
                "severity": r.severity,
                "sparql": r.sparql,
                "enabled": r.enabled,
            }
            for r in rows
            if r.kind == "custom"
        ],
    }


@router.get("/{ontology_id}/lint/config")
def get_config(
    ontology_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Read the ontology's lint config (defaults: nothing disabled)."""
    oid = _lint_owned(user, session, ontology_id)
    return respond(_config_payload(session, oid))


@router.put("/{ontology_id}/lint/config")
def put_config(
    ontology_id: str,
    body: LintConfigIn,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Overwrite the whole lint config (no lock — never touches the file)."""
    oid = _lint_owned(user, session, ontology_id)
    if any(c.severity not in ("error", "warning", "info") for c in body.custom):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "severity must be error|warning|info")
    customs = [c.model_dump() for c in body.custom]
    LintRuleRepository(session).replace_all(oid, body.disabled, customs)
    return respond(_config_payload(session, oid))


class LintRunIn(CamelModel):
    """Run request: optionally scope to one rule (settings「测试」button)."""

    only_rule_id: str | None = None


@router.post("/{ontology_id}/lint/run")
def run_lint(
    ontology_id: str,
    body: LintRunIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Run the whole lint set manually (spec §0: 仅手动).

    Walks the pooled editable Store — read-only, never mutated, never
    evicted here; a pool miss still pays the parse, which is why runs
    are never automatic.
    """
    row, ix = _owned(request, user, ontology_id, session)
    rows = LintRuleRepository(session).list_for(row.id)
    disabled = {r.key for r in rows if r.kind == "builtin" and r.key is not None}
    custom = [
        CustomRuleSpec(
            id=str(r.id),
            name=r.name or "",
            severity=r.severity or "info",
            sparql=r.sparql or "",
        )
        for r in rows
        if r.kind == "custom" and r.enabled
    ]
    cache: OntologyCache = request.app.state.cache
    store, _ = cache.store_for(row, load_store)
    t0 = time.perf_counter()
    report = run_lint_engine(store, ix.ir, disabled, custom, only_rule_id=body.only_rule_id)
    return respond(
        _camel(
            {
                "fileHash": row.file_hash,
                "durationMs": round((time.perf_counter() - t0) * 1000, 1),
                "counts": report.counts,
                "results": [r.model_dump() for r in report.results],
            }
        )
    )
