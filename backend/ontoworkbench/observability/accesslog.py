"""Structured access log middleware; slow requests escalate to WARNING."""

from __future__ import annotations

import time

import structlog

from ontoworkbench.observability.middleware import request_id_ctx, user_id_ctx

_log = structlog.get_logger("ow.access")
SLOW_MS = 5000


async def access_log_middleware(request, call_next):
    """Log one JSON line per request with duration, request id, user id."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    entry = _log.info if duration_ms < SLOW_MS else _log.warning
    entry(
        "http.request",
        method=request.method,
        path=request.url.path,
        status=response.status_code,
        duration_ms=duration_ms,
        request_id=request_id_ctx.get(),
        user_id=user_id_ctx.get(),
    )
    return response
