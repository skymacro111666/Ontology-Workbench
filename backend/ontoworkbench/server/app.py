"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ontoworkbench.config import Settings
from ontoworkbench.observability.middleware import request_id_ctx, request_id_middleware
from ontoworkbench.server.envelope import HTTP_OF, ApiError, ErrorCode


def _envelope(code: ErrorCode, message: str, data=None, hint: str | None = None) -> dict:
    return {
        "code": code.value,
        "message": message,
        "data": data,
        "hint": hint,
        "request_id": request_id_ctx.get(),
    }


def create_app(settings: Settings) -> FastAPI:
    """Assemble the app: middlewares + handlers + routers."""
    app = FastAPI(title="Ontology Workbench", docs_url="/api/docs")

    app.middleware("http")(request_id_middleware)

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_OF[exc.code],
            content=_envelope(exc.code, exc.message, None, exc.hint),
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = ErrorCode.NOT_FOUND if exc.status_code == 404 else ErrorCode.INTERNAL_ERROR
        return JSONResponse(status_code=exc.status_code, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = str(exc.errors()[:3])
        return JSONResponse(
            status_code=422,
            content=_envelope(
                ErrorCode.VALIDATION_ERROR, "Invalid request parameters", hint=detail
            ),
        )

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=_envelope(ErrorCode.INTERNAL_ERROR, "Internal Server Error"),
        )

    @app.get("/api/health")
    async def health() -> dict:
        return _envelope(ErrorCode.OK, "success", {"status": "up"})

    return app
