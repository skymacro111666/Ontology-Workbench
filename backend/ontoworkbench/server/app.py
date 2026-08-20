"""FastAPI application factory."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ontoworkbench.config import Settings
from ontoworkbench.observability.accesslog import access_log_middleware
from ontoworkbench.observability.logging import setup_logging
from ontoworkbench.observability.metrics import configure_metrics
from ontoworkbench.observability.middleware import request_id_ctx, request_id_middleware
from ontoworkbench.server.envelope import HTTP_OF, ApiError, ErrorCode
from ontoworkbench.server.routers import auth as auth_router

# Local development origins (vite dev server); the built SPA is same-origin.
_LOCAL_DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]


def _envelope(code: ErrorCode, message: str, data=None, hint: str | None = None) -> dict:
    return {
        "code": code.value,
        "message": message,
        "data": data,
        "hint": hint,
        "request_id": request_id_ctx.get(),
    }


def _code_for_http_status(status: int) -> tuple[ErrorCode, int]:
    """Map a Starlette HTTPException status to (envelope code, response status).

    The spec §6 table has no METHOD_NOT_ALLOWED, so 405 collapses into
    NOT_FOUND at 404 (method-addressed resource not found, GitHub-API style).
    """
    if status in (404, 405):
        return ErrorCode.NOT_FOUND, 404
    if status >= 500:
        return ErrorCode.INTERNAL_ERROR, 500
    return ErrorCode.VALIDATION_ERROR, status


def create_app(settings: Settings) -> FastAPI:
    """Assemble the app: middlewares + handlers + routers."""
    setup_logging(settings.log_dir, settings.log_level)
    app = FastAPI(title="Ontology Workbench", docs_url="/api/docs")
    app.state.settings = settings

    # Register order matters: the LAST registered runs outermost. request-id
    # must be outermost so the access log (inner) inherits its contextvar.
    app.middleware("http")(access_log_middleware)
    app.middleware("http")(request_id_middleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_LOCAL_DEV_ORIGINS,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    app.include_router(auth_router.router)
    configure_metrics(app)

    @app.exception_handler(ApiError)
    async def on_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=HTTP_OF[exc.code],
            content=_envelope(exc.code, exc.message, None, exc.hint),
        )

    @app.exception_handler(StarletteHTTPException)
    async def on_http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, status = _code_for_http_status(exc.status_code)
        return JSONResponse(status_code=status, content=_envelope(code, str(exc.detail)))

    @app.exception_handler(RequestValidationError)
    async def on_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # loc/msg/type only — pydantic's raw error dicts embed the rejected
        # input values, which must not be echoed into the response
        safe = [
            {"loc": list(e.get("loc", [])), "msg": e.get("msg"), "type": e.get("type")}
            for e in exc.errors()[:3]
        ]
        return JSONResponse(
            status_code=422,
            content=_envelope(
                ErrorCode.VALIDATION_ERROR, "Invalid request parameters", hint=str(safe)
            ),
        )

    @app.exception_handler(Exception)
    async def on_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # ServerErrorMiddleware bypasses our middleware, so the request-id
        # header must be set here to keep header/body/log ids identical
        response = JSONResponse(
            status_code=500,
            content=_envelope(ErrorCode.INTERNAL_ERROR, "Internal Server Error"),
        )
        response.headers["X-Request-ID"] = request_id_ctx.get()
        return response

    @app.get("/api/health")
    async def health() -> dict:
        return _envelope(ErrorCode.OK, "success", {"status": "up"})

    return app
