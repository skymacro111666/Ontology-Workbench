"""Tool registration + mcp.tool audit event (spec §6)."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from ontoworkbench.server.mcp.auth import label_ctx
from ontoworkbench.server.mcp.errors import LoopbackError, to_tool_error

_tool_log = structlog.get_logger("ow.mcp")


def audit(name: str, fn: Callable) -> Callable:
    """Wrap a tool coroutine: timing + result code + agent label, per logging.md style.

    Correlation ids (B3 telemetry) come from the SDK-injected Context the
    tool functions declare: request_id identifies the call; mcp_session_id
    is read tolerantly because stateless HTTP need not carry one. Tools bind
    their own measurement fields (query/hits/sizes) via structlog contextvars;
    merge_contextvars folds everything into the single mcp.tool event, and
    clear_contextvars keeps bindings from leaking into the next request.
    """

    @wraps(fn)
    async def wrapper(**kwargs: Any) -> Any:
        started = time.perf_counter()
        code = "OK"
        ctx = kwargs.get("ctx")
        if ctx is not None:
            bind_contextvars(request_id=str(getattr(ctx, "request_id", "") or ""))
            try:
                session = getattr(ctx, "session", None)
                bind_contextvars(mcp_session_id=getattr(session, "mcp_session_id", None))
            except Exception:  # session access is transport-dependent
                pass
        try:
            return await fn(**kwargs)
        except LoopbackError as exc:
            code = exc.code
            raise to_tool_error(exc) from None
        except Exception:
            code = "INTERNAL_ERROR"
            raise
        finally:
            _tool_log.info(
                "mcp.tool",
                tool=name,
                label=label_ctx.get(),
                oid=kwargs.get("oid"),
                result=code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )
            clear_contextvars()

    return wrapper


def register_tools(mcp, loopback) -> None:
    """Register the v1 read-only tool set (filled by tools/read.py in T8)."""
    from ontoworkbench.server.mcp.tools.read import register

    register(mcp, loopback, audit)
