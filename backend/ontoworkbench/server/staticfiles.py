"""SPA static serving with history fallback."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from ontoworkbench.server.envelope import ErrorCode, error_body

# Paths that must never fall back to index.html: unknown API/metrics routes
# keep returning the JSON envelope exactly like unmatched pre-mount routes.
_JSON_404_PREFIXES = ("api/", "metrics")


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Serve the file; SPA-route misses return index.html, API stays JSON."""
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if path.startswith(_JSON_404_PREFIXES):
                return JSONResponse(
                    status_code=404,
                    content=error_body(ErrorCode.NOT_FOUND, "Not Found"),
                )
            return await super().get_response("index.html", scope)
