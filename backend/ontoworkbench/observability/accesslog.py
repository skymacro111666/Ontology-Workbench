"""Structured access log middleware; slow requests escalate to WARNING."""

from __future__ import annotations

import time
from datetime import UTC, datetime

import structlog

from ontoworkbench.observability.middleware import request_id_ctx

_log = structlog.get_logger("ow.access")
SLOW_MS = 5000
_USER_AGENT_MAX = 200


def _client_ip(request) -> str:
    """First X-Forwarded-For hop when a proxy set it, else the socket peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",", 1)[0].strip()
    return request.client.host if request.client else "unknown"


async def access_log_middleware(request, call_next):
    """Log one JSON line per request with duration, request id, user id.

    user_id comes from request.state, NOT user_id_ctx: the contextvar is set
    inside the route, and BaseHTTPMiddleware's call_next runs downstream in
    a child task whose contextvar writes never flow back here. request.state
    shares the scope dict, so the route-side writes are visible. Every line
    carries a value — "anonymous" when no user authenticated.

    route/ontology_id are read after call_next: the scope only carries the
    matched route once routing has run. Metrics aggregate on route (bounded
    cardinality); log queries join on ontology_id.
    """
    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    route = request.scope.get("route")
    params = request.scope.get("path_params") or {}
    user_agent = request.headers.get("user-agent")
    entry = _log.info if duration_ms < SLOW_MS else _log.warning
    entry(
        "http.request",
        method=request.method,
        path=request.url.path,
        # Unmatched paths (404) have no route object — the raw path stands in.
        route=getattr(route, "path", None) or request.url.path,
        ontology_id=params.get("ontology_id"),
        status=response.status_code,
        duration_ms=duration_ms,
        started_at=started_at,
        client_ip=_client_ip(request),
        user_agent=user_agent[:_USER_AGENT_MAX] if user_agent else None,
        request_id=request_id_ctx.get(),
        user_id=getattr(request.state, "user_id", None) or "anonymous",
    )
    return response
