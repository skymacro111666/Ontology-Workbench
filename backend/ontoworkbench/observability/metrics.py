"""Prometheus instrumentation: HTTP defaults + business metrics."""

from __future__ import annotations

from fastapi import FastAPI
from prometheus_client import Counter, Gauge, Histogram
from prometheus_fastapi_instrumentator import Instrumentator

ow_parse_seconds = Histogram("ow_parse_seconds", "Ontology parse duration", ["format"])
ow_uploads_total = Counter("ow_uploads_total", "Uploaded ontologies", ["result"])
ow_cached_ontologies = Gauge("ow_cached_ontologies", "Ontologies held in memory cache")


def configure_metrics(app: FastAPI) -> None:
    """Expose GET /metrics (no auth) with default + custom metrics."""
    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)
