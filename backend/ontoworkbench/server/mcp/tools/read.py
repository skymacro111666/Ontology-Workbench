"""v1 read-only tools (spec §7): REST passthrough via the loopback."""

from __future__ import annotations

from typing import Any


def register(mcp, loopback, audit) -> None:
    """Register tools onto the MCP server, each wrapped for audit."""

    async def _list_ontologies() -> dict[str, Any]:
        return await loopback.call("GET", "/api/v1/ontologies")

    async def _get_ontology(oid: str) -> dict[str, Any]:
        return await loopback.call("GET", f"/api/v1/ontologies/{oid}/meta")

    # name= is explicit: the audit wrapper's @wraps keeps the underscore-
    # prefixed inner name, which the SDK would otherwise use verbatim.
    mcp.tool(name="list_ontologies")(audit("list_ontologies", _list_ontologies))
    mcp.tool(name="get_ontology")(audit("get_ontology", _get_ontology))
