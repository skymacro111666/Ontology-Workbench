"""Prometheus instrumentation: HTTP defaults + business metrics."""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

ow_parse_seconds = Histogram("ow_parse_seconds", "Ontology parse duration", ["format"])
ow_build_seconds = Histogram("ow_build_seconds", "IR build duration")
ow_uploads_total = Counter("ow_uploads_total", "Uploaded ontologies", ["result"])
ow_cached_ontologies = Gauge("ow_cached_ontologies", "Ontologies held in memory cache")
ow_cached_stores = Gauge("ow_cached_stores", "Editable Stores held in memory cache")
ow_ir_cache_reads_total = Counter("ow_ir_cache_reads_total", "Disk IR cache reads", ["result"])
ow_autosave_total = Counter("ow_autosave_total", "Debounced autosave outcomes", ["result"])
ow_validate_seconds = Histogram("ow_validate_seconds", "SHACL validation duration", ["engine"])
ow_validate_runs_total = Counter("ow_validate_runs_total", "SHACL validation runs", ["conforms"])
ow_validate_exports_total = Counter(
    "ow_validate_exports_total", "SHACL validation exports", ["format"]
)
ow_query_exports_total = Counter("ow_query_exports_total", "SPARQL query exports", ["format"])


def configure_metrics(app: FastAPI) -> None:
    """Expose GET /metrics (no auth) with default + custom metrics."""
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
