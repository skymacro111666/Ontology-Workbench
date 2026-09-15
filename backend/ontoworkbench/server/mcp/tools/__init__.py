"""Tool registration + mcp.tool audit event (spec §6)."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

import structlog

from ontoworkbench.server.mcp.auth import label_ctx
from ontoworkbench.server.mcp.errors import LoopbackError, to_tool_error

_tool_log = structlog.get_logger("ow.mcp")


def audit(name: str, fn: Callable) -> Callable:
    """Wrap a tool coroutine: timing + result code + agent label, per logging.md style."""

    @wraps(fn)
    async def wrapper(**kwargs: Any) -> Any:
        started = time.perf_counter()
        code = "OK"
        try:
            return await fn(**kwargs)
        except LoopbackError as exc:
            code = exc.code
            raise to_tool_error(exc) from None
        finally:
            _tool_log.info(
                "mcp.tool",
                tool=name,
                label=label_ctx.get(),
                oid=kwargs.get("oid"),
                result=code,
                duration_ms=round((time.perf_counter() - started) * 1000, 1),
            )

    return wrapper


def register_tools(mcp, loopback) -> None:
    """Register the v1 read-only tool set (filled by tools/read.py in T8)."""
    from ontoworkbench.server.mcp.tools.read import register

    register(mcp, loopback, audit)
