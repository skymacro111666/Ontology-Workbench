"""SPA static serving with history fallback."""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from ontoworkbench.server.envelope import ErrorCode, error_body


# Paths that must never fall back to index.html: unknown API/metrics routes
# keep returning the JSON envelope exactly like unmatched pre-mount routes.
def _is_api_path(path: str) -> bool:
    return path.startswith("api/") or path == "metrics" or path.startswith("metrics/")


class SPAStaticFiles(StaticFiles):
    """StaticFiles that falls back to index.html for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """Serve the file; SPA-route misses return index.html, API stays JSON.

        Caching: index.html revalidates every load (no-cache) so a rebuilt
        bundle lands on the next refresh — without the header browsers keep
        heuristic-cached stale entries. Hashed /assets/* are immutable:
        their filename changes with content, so they cache for a year.
        """
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404:
                raise
            if _is_api_path(path):
                return JSONResponse(
                    status_code=404,
                    content=error_body(ErrorCode.NOT_FOUND, "Not Found"),
                )
            response = await super().get_response("index.html", scope)
            path = "index.html"
        if path in ("", ".") or path.endswith("index.html"):
            response.headers["Cache-Control"] = "no-cache"
        elif path.startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
