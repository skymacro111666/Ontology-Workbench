"""Request-ID middleware: header + response body + logs share one id."""

import re
from contextvars import ContextVar
from uuid import uuid4

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
user_id_ctx: ContextVar[str | None] = ContextVar("user_id", default=None)

# Client-supplied ids must stay header-safe and short; anything else is replaced
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _sanitize(raw: str | None) -> str:
    """Accept a well-formed client id, else mint a fresh one."""
    if raw and _VALID_REQUEST_ID.match(raw):
        return raw
    return uuid4().hex[:12]


async def request_id_middleware(request, call_next):
    """Bind one request id to the contextvar and the X-Request-ID header."""
    rid = _sanitize(request.headers.get("x-request-id"))
    request_id_ctx.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response
