"""Request-ID middleware: header + response body + logs share one id."""

from contextvars import ContextVar
from uuid import uuid4

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)


async def request_id_middleware(request, call_next):
    """Bind one request id to the contextvar and the X-Request-ID header."""
    rid = request.headers.get("x-request-id") or uuid4().hex[:12]
    request_id_ctx.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response
