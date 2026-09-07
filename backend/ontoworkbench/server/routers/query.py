"""SPARQL query endpoint — the 查询 view's read-only console (M1, spec 2026-09-07).

Runs store.query() on the pooled editable Store. Read-only is
engine-enforced: pyoxigraph splits query() from update(), and an UPDATE
statement submitted through query() fails to parse — no keyword filtering
to bypass. The shared pool means a query concurrent with an in-flight
edit may observe not-yet-persisted changes (same stance as lint; the
debounced save self-heals). Queries see ASSERTED triples only — no OWL
reasoning; transitive subclass closure goes through property paths.
"""

from __future__ import annotations

import time
from typing import Any

import pyoxigraph as ox
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
from sqlalchemy.orm import Session

from ontoworkbench.core.prefixes import PrefixMap
from ontoworkbench.db.models import User
from ontoworkbench.db.session import get_session
from ontoworkbench.server.cache import load_store
from ontoworkbench.server.deps import get_current_user
from ontoworkbench.server.envelope import ApiError, ErrorCode, respond
from ontoworkbench.server.routers.browse import _camel, _owned

router = APIRouter(prefix="/api/ontologies", tags=["query"])

# Rows (SELECT) / triples (CONSTRUCT, DESCRIBE) served per run; the cap
# guards payload size, not evaluation time — pyoxigraph exposes no query
# timeout, accepted for the single-admin self-hosted deployment.
MAX_QUERY_ROWS = 1000


class QueryIn(BaseModel):
    """One SPARQL query string (camelCase wire style, see envelope)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    qs: str


def _term_json(
    term: ox.NamedNode | ox.BlankNode | ox.Literal | None, prefixes: PrefixMap
) -> dict[str, Any] | None:
    """One result cell: type + lexical value, plus curie/lang/datatype."""
    if term is None:
        return None
    if isinstance(term, ox.NamedNode):
        curie = prefixes.curie_for(term.value)
        return {
            "type": "iri",
            "value": term.value,
            **({"curie": f"{curie[0]}:{curie[1]}"} if curie else {}),
        }
    if isinstance(term, ox.BlankNode):
        return {"type": "bnode", "value": term.value}
    # Literal: keep the lexical form; language/datatype travel as metadata.
    lit: dict[str, Any] = {"type": "literal", "value": term.value}
    if term.language:
        lit["language"] = term.language
    if (
        term.datatype is not None
        and term.datatype.value != "http://www.w3.org/1999/02/22-rdf-syntax-ns#langString"
    ):
        lit["datatype"] = term.datatype.value
    return lit


def _run_query(qs: str, store: ox.Store, prefixes: PrefixMap) -> dict[str, Any]:
    """Execute one query and shape the payload for the three result kinds."""
    t0 = time.perf_counter()
    try:
        result = store.query(qs)
    except SyntaxError as e:  # pyoxigraph raises the builtin on parse rejects
        # UPDATE statements and syntax garbage both land here: query() only
        # ever parses read-only SPARQL (engine-enforced, spec 2026-09-07).
        raise ApiError(
            ErrorCode.QUERY_INVALID,
            "The query is not valid read-only SPARQL",
            hint=str(e).strip() or None,
        ) from e
    elapsed = round((time.perf_counter() - t0) * 1000, 1)
    if isinstance(result, ox.QueryBoolean):
        return {"kind": "ask", "boolean": bool(result), "elapsedMs": elapsed}
    if isinstance(result, ox.QueryTriples):
        triples = []
        for i, triple in enumerate(result):
            if i >= MAX_QUERY_ROWS:
                break
            triples.append(triple)
        serialized = ox.serialize(triples, format=ox.RdfFormat.TURTLE)
        return {
            "kind": "construct",
            "tripleCount": len(triples),
            "truncated": _is_truncated(result, len(triples)),
            "turtle": (serialized or b"").decode(),
            "elapsedMs": elapsed,
        }
    # SELECT: column order from the solutions' declared variables.
    columns = [str(v).lstrip("?") for v in result.variables]
    rows: list[dict[str, Any]] = []
    truncated = False
    for solution in result:
        if len(rows) >= MAX_QUERY_ROWS:
            truncated = True
            break
        row: dict[str, Any] = {}
        for name in columns:
            try:
                row[name] = _term_json(solution[name], prefixes)
            except KeyError:  # UNBOUND variable in this solution
                row[name] = None
        rows.append(row)
    return {
        "kind": "select",
        "columns": columns,
        "rows": rows,
        "rowCount": len(rows),
        "truncated": truncated,
        "elapsedMs": elapsed,
    }


def _is_truncated(result: ox.QueryTriples, served: int) -> bool:
    """True when more triples remain past the cap (probe without draining)."""
    if served < MAX_QUERY_ROWS:
        return False
    for _ in result:
        return True
    return False


@router.post("/{ontology_id}/query")
def query(
    ontology_id: str,
    body: QueryIn,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Run one read-only SPARQL query over the ontology's pooled Store."""
    row, _ = _owned(request, user, ontology_id, session)
    store, prefixes = request.app.state.cache.store_for(row, load_store)
    return respond(_camel(_run_query(body.qs, store, prefixes)))
