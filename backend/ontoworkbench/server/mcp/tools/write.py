"""P4 write tools: R2RML mapping read + gated update via the loopback.

The write pair is a pure passthrough like the read set — the three-layer
gate, the optimistic lock and the rollback slot all live in the REST PUT.
Only the error mapping is local: findings hints are the agent's actionable
payload and must survive untruncated (the shared 500-cap guard is a
read-tool noise guard, spec §4).
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.context import Context
from mcp.server.mcpserver.exceptions import ToolError

from ontoworkbench.server.mcp.errors import LoopbackError


def _write_error(exc: LoopbackError) -> ToolError:
    """Full-fidelity mapping: code + message + hint, no truncation.

    The ``code`` attribute feeds the audit wrapper's telemetry so a 422
    logs result=R2RML_INVALID instead of INTERNAL_ERROR.
    """
    text = f"{exc.code}: {exc.message}"
    if exc.hint:
        text += f"\n{exc.hint}"
    err = ToolError(text)
    err.code = exc.code
    return err


def register(mcp, loopback, audit) -> None:
    """Register the P4 write tools onto the FastMCP instance."""

    async def _get_r2rml(oid: str, ctx: Context) -> dict[str, Any]:
        return await loopback.call("GET", f"/api/v1/ontologies/{oid}/r2rml")

    async def _update_r2rml(oid: str, content: str, base_hash: str, ctx: Context) -> dict[str, Any]:
        try:
            return await loopback.call(
                "PUT",
                f"/api/v1/ontologies/{oid}/r2rml",
                json_body={"content": content, "baseHash": base_hash},
            )
        except LoopbackError as exc:
            raise _write_error(exc) from None

    mcp.tool(
        name="get_r2rml",
        description=(
            "Read one ontology's R2RML mapping (Turtle + contentHash + parsed "
            "table/class correspondences). Call this before update_r2rml to get "
            "the current contentHash."
        ),
    )(audit("get_r2rml", _get_r2rml))
    mcp.tool(
        name="update_r2rml",
        description=(
            "Replace the R2RML mapping text. Must pass the same three-layer gate "
            "as the web editor (subset shape + snapshot semantics); 422 returns "
            "located findings per layer. base_hash is the contentHash from "
            "get_r2rml; a mismatch gives 409 R2RML_STALE — re-fetch and replay."
        ),
    )(audit("update_r2rml", _update_r2rml))
