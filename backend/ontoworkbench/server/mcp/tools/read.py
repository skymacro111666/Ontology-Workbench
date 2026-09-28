"""v1 read-only tools (spec §7): REST passthrough via the loopback.

All truncating tools carry their own metadata (truncated flag + limit) and a
next-step hint — never truncate silently (ContextPack contract discipline,
spec D9①). Single-entity payloads are never half-cut.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

MAX_EXPORT_BYTES = 200_000


def _eid(eid: str) -> str:
    """Path-safe entity id (curies contain ':'; the :path converter accepts the rest)."""
    return quote(eid, safe="")


def _json_list(items: list) -> str:
    """One text block carrying the whole list.

    The SDK unrolls a plain list return into one content item per element,
    and clients that read only content[0] would lose all but the first —
    pre-serialized JSON keeps the REST payload shape intact on the wire.
    """
    return json.dumps(items, ensure_ascii=False)


def register(mcp, loopback, audit) -> None:
    """Register the ten v1 tools onto the FastMCP instance."""

    async def _list_ontologies() -> dict[str, Any]:
        data = await loopback.call("GET", "/api/v1/ontologies")
        # Agent-facing guidance lives at the MCP layer, not the REST payload
        # (browser/REST consumers never see this note) — the A2 stand-in for
        # a session manifest: on-demand, not pre-injected.
        data["note"] = (
            "newest first; call get_ontology(id) for prefixes/profile, "
            "search_entities(id, q) to locate entities before get_entity"
        )
        return data

    async def _get_ontology(oid: str) -> dict[str, Any]:
        return await loopback.call("GET", f"/api/v1/ontologies/{oid}/meta")

    async def _search_entities(oid: str, q: str, kind: str | None = None, limit: int = 20) -> str:
        params: dict[str, Any] = {"q": q, "limit": limit}
        if kind:
            params["type"] = kind
        hits = await loopback.call("GET", f"/api/v1/ontologies/{oid}/search", params=params)
        # Same envelope discipline as export_file below: never truncate
        # silently (D9①). The engine breaks early at limit, so limitReached
        # only says "more may exist", not how many.
        return json.dumps(
            {
                "items": hits,
                "limit": limit,
                "limitReached": len(hits) >= limit,
                "note": (
                    "each item carries matched_field (localname/label/comment) "
                    "as its hit rationale; refine q or raise limit when "
                    "limitReached is true"
                ),
            },
            ensure_ascii=False,
        )

    async def _get_entity(oid: str, eid: str) -> dict[str, Any]:
        return await loopback.call("GET", f"/api/v1/ontologies/{oid}/entities/{_eid(eid)}")

    async def _get_class_tree(oid: str, parent: str | None = None) -> str:
        params = {"parent": parent} if parent else None
        nodes = await loopback.call("GET", f"/api/v1/ontologies/{oid}/tree", params=params)
        return _json_list(nodes)

    async def _get_instances(oid: str, eid: str) -> dict[str, Any]:
        return await loopback.call(
            "GET", f"/api/v1/ontologies/{oid}/entities/{_eid(eid)}/instances"
        )

    async def _run_lint(oid: str) -> dict[str, Any]:
        return await loopback.call("POST", f"/api/v1/ontologies/{oid}/lint/run", json_body={})

    async def _run_validation(oid: str, include_deprecated: bool = True) -> dict[str, Any]:
        return await loopback.call(
            "POST",
            f"/api/v1/ontologies/{oid}/validation/run",
            json_body={"includeDeprecated": include_deprecated},
        )

    async def _sparql_query(oid: str, qs: str) -> dict[str, Any]:
        # 1000-row engine cap arrives in the REST payload (truncated flag included).
        return await loopback.call("POST", f"/api/v1/ontologies/{oid}/query", json_body={"qs": qs})

    # rdf_format forwards verbatim; the API accepts turtle / json-ld / rdf-xml
    # (its error lists them) — "ttl" is the file extension, not a format key.
    async def _export_file(oid: str, rdf_format: str = "turtle") -> dict[str, Any]:
        out = await loopback.call(
            "GET", f"/api/v1/ontologies/{oid}/export/file", params={"format": rdf_format}
        )
        content: str = out.get("content", "")
        if len(content.encode()) > MAX_EXPORT_BYTES:
            return {
                "filename": out.get("filename"),
                "mediaType": out.get("mediaType"),
                "truncated": True,
                "maxBytes": MAX_EXPORT_BYTES,
                "content": content[:MAX_EXPORT_BYTES],
                "hint": "output exceeds the export budget — use sparql_query for targeted slices",
            }
        return {
            "filename": out.get("filename"),
            "mediaType": out.get("mediaType"),
            "truncated": False,
            "content": content,
        }

    # name=/description= are explicit: the audit wrapper's @wraps keeps the
    # underscore-prefixed inner name and empty docstring, which the SDK would
    # otherwise use verbatim (A2: agents get an unnamed-in-practice tool).
    mcp.tool(
        name="list_ontologies",
        description=(
            "List every ontology owned by this credential, newest first, with "
            "class/property/instance/axiom counts. Start here: pick an id, then "
            "call get_ontology or search_entities with it."
        ),
    )(audit("list_ontologies", _list_ontologies))
    mcp.tool(
        name="get_ontology",
        description=(
            "Metadata for one ontology: counts, prefixes, save state, and the "
            "OWL 2 profile report when available."
        ),
    )(audit("get_ontology", _get_ontology))
    mcp.tool(
        name="search_entities",
        description=(
            "Case-insensitive substring search over localname/label/comment "
            "(individuals: localname/label only). Each hit carries the eid for "
            "get_entity and matched_field saying which field hit; limitReached "
            "marks a possible truncation at the limit."
        ),
    )(audit("search_entities", _search_entities))
    mcp.tool(
        name="get_entity",
        description=(
            "Full detail for one class/property/individual by eid (from "
            "search_entities or get_class_tree): labels, Manchester-syntax "
            "axioms, and neighbors."
        ),
    )(audit("get_entity", _get_entity))
    mcp.tool(
        name="get_class_tree",
        description=(
            "One level of the class tree: roots when parent is omitted, direct "
            "children otherwise. Walk lazily via parent (nodes carry "
            "children_count) instead of trying to fetch the whole tree."
        ),
    )(audit("get_class_tree", _get_class_tree))
    mcp.tool(
        name="get_instances",
        description=("Individuals asserted as this class, with their property assertions."),
    )(audit("get_instances", _get_instances))
    mcp.tool(
        name="run_lint",
        description=(
            "Run the ontology lint checks (naming, annotation, deprecated usage) "
            "and return the findings list."
        ),
    )(audit("run_lint", _run_lint))
    mcp.tool(
        name="run_validation",
        description=(
            "Run instance-level validation. Without validation shapes configured "
            "the error response explains that shapes are managed in the web UI."
        ),
    )(audit("run_validation", _run_validation))
    mcp.tool(
        name="sparql_query",
        description=(
            "Run a read-only SPARQL SELECT against one ontology. The engine caps "
            "output at 1000 rows; a truncated flag in the payload marks it."
        ),
    )(audit("sparql_query", _sparql_query))
    mcp.tool(
        name="export_file",
        description=(
            "Export the ontology source as turtle / json-ld / rdf-xml. Output "
            "over 200 KB is truncated with a hint pointing to sparql_query for "
            "targeted slices."
        ),
    )(audit("export_file", _export_file))
