"""Legacy graph editing pipeline for the routers not yet on the Store.

instances.py rides every helper here and lint.py rides load_graph, both
through entities.py's compatibility wrappers. This is a verbatim move of
the pre-migration entities.py code so entities.py itself can drop the
graph engine; the instances migration task deletes this module together
with its last caller.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import Request
from rdflib import Graph, URIRef
from sqlalchemy.orm import Session

from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.core.ir_cache import write_ir_cache
from ontoworkbench.core.parsing import serialize_graph
from ontoworkbench.core.store import LocalUserDirStore
from ontoworkbench.db.models import Ontology
from ontoworkbench.db.repositories import OntologyRepository
from ontoworkbench.observability.metrics import ow_build_seconds, ow_uploads_total
from ontoworkbench.server.cache import OntologyCache
from ontoworkbench.server.envelope import ApiError, ErrorCode
from ontoworkbench.server.routers.ontologies import MAX_UPLOAD, title_of

_NAME_RE = re.compile(r"^[A-Za-z_][\w.-]*$")


def load_graph(row: Ontology) -> Graph:
    """Parse the stored file back into a mutable graph."""
    return Graph().parse(data=Path(row.storage_path).read_bytes(), format=_rdf_format(row.format))


def _rdf_format(fmt: str) -> str:
    """Internal format name → serializer name."""
    return {"turtle": "turtle", "rdfxml": "xml", "jsonld": "json-ld"}[fmt]


def iri_for(graph: Graph, prefix: str, name: str) -> URIRef:
    """Mint prefix:name; unknown prefix or bad name is a 422."""
    if not _NAME_RE.match(name):
        raise ApiError(
            ErrorCode.VALIDATION_ERROR,
            f"Invalid name '{name}'",
            "Use a letter/underscore start, then letters, digits, ., - or _.",
        )
    for p, ns in graph.namespaces():
        if p == prefix:
            return URIRef(str(ns) + name)
    known = ", ".join(sorted({p for p, _ in graph.namespaces() if p})) or "(none)"
    raise ApiError(
        ErrorCode.VALIDATION_ERROR,
        f"Unknown prefix '{prefix}'",
        f"Known prefixes: {known}",
    ) from None


def reject_duplicate(graph: Graph, iri: URIRef) -> None:
    """Refuse to mint an IRI that already carries triples."""
    if any(graph.triples((iri, None, None))) or any(graph.triples((None, None, iri))):
        raise ApiError(
            ErrorCode.DUPLICATE_ENTITY,
            f"'{iri}' is already used in this ontology",
            "Pick a different name or prefix.",
        )


def entity_payload(graph: Graph, iri: URIRef, kind: str) -> dict[str, Any]:
    """Small entity reference for write responses (full data via GET)."""
    try:
        curie = graph.compute_qname(iri)[2]
        prefix = graph.compute_qname(iri)[0]
        curie = f"{prefix}:{curie}"
    except Exception:
        curie = str(iri)
    return {"eid": str(iri), "curie": curie, "type": kind}


def persist(
    request: Request, session: Session, row: Ontology, graph: Graph
) -> tuple[Ontology, Any]:
    """Serialize → build from the mutated graph → atomic write → row/cache refresh."""
    data = serialize_graph(graph, row.format)
    if len(data) > MAX_UPLOAD:
        ow_uploads_total.labels("too_large").inc()
        raise ApiError(ErrorCode.UPLOAD_TOO_LARGE, "File exceeds the 150MB limit")
    # The mutated in-memory graph IS the data just serialized — building the
    # IR from it directly drops the old re-parse-for-validation (a full
    # second parse per edit, ~3min on a 130MB ontology).
    old_parse_ms = (row.stats_json or {}).get("parse_ms")
    t0 = time.perf_counter()
    with ow_build_seconds.time():
        ir = build_ir(graph)
    build_ms = (time.perf_counter() - t0) * 1000.0

    store: LocalUserDirStore = request.app.state.store
    store.save(row.owner_user_id, UUID(str(row.id)), row.filename, data)
    repos = OntologyRepository(session)
    row = (
        repos.update(
            row.id,
            title=title_of(graph, row.filename),
            class_count=ir.counts.class_count,
            property_count=ir.counts.property_count,
            axiom_count=ir.counts.axiom_count,
            instance_count=ir.counts.individual_count,
            stats_json={
                "prefixes": ir.prefixes,
                "parse_ms": old_parse_ms,
                "build_ms": round(build_ms, 1),
            },
            file_size_bytes=len(data),
            file_hash=LocalUserDirStore.file_hash(data),
        )
        or row
    )
    # The disk cache must move with the file: the next cold start would
    # otherwise re-pay the full parse for this ontology.
    write_ir_cache(Path(row.storage_path), ir, row.file_hash)
    cache: OntologyCache = request.app.state.cache
    cache.indexes_for(row, lambda r: build_indexes(ir))
    return row, ir
