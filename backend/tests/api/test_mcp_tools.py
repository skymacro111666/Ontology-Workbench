"""Tool contracts over the mounted app (spec §7 + §11.3): happy paths, pointers, truncation."""

import json

import pytest
from fastapi.testclient import TestClient

from tests.api.test_mcp_mount import _post_rpc, mcp_env  # noqa: F401

# mcp_env is imported only so pytest can resolve the fixture from another test
# module; every test then takes it as a parameter, which shadows the import
# (the F811 noqa on each def below).


def _tool(client: TestClient, name: str, arguments: dict) -> dict:
    """Call one tool via JSON-RPC and parse its text content as JSON."""
    msg = _post_rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        client.agent_token,
    )
    assert "result" in msg, msg
    return json.loads(msg["result"]["content"][0]["text"])


def _tools(client: TestClient) -> list[str]:
    """List the registered tool names over JSON-RPC."""
    msg = _post_rpc(client, {"jsonrpc": "2.0", "id": 8, "method": "tools/list"}, client.agent_token)
    return [t["name"] for t in msg["result"]["tools"]]


def _first_oid(client: TestClient) -> str:
    """The pizza sample's oid, read over REST with the human JWT."""
    r = client.get("/api/v1/ontologies", headers={"Authorization": f"Bearer {client.jwt}"})
    return r.json()["data"]["items"][0]["id"]


def test_all_ten_tools_registered(mcp_env: TestClient) -> None:  # noqa: F811
    """tools/list carries exactly the ten v1 tool names (spec §7)."""
    assert set(_tools(mcp_env)) == {
        "list_ontologies",
        "get_ontology",
        "search_entities",
        "get_entity",
        "get_class_tree",
        "get_instances",
        "run_lint",
        "run_validation",
        "sparql_query",
        "export_file",
    }


def test_all_tool_descriptions_present(mcp_env: TestClient) -> None:  # noqa: F811
    """tools/list ships a non-empty description for every v1 tool (A2 discipline).

    Would fail if a tool were registered without description= (the SDK falls
    back to the empty docstring, leaving agents an unnamed-in-practice tool).
    """
    msg = _post_rpc(
        mcp_env, {"jsonrpc": "2.0", "id": 8, "method": "tools/list"}, mcp_env.agent_token
    )
    empty = [t["name"] for t in msg["result"]["tools"] if not t.get("description", "").strip()]
    assert empty == [], f"tools without a description: {empty}"


def test_search_entity_tree_instances(mcp_env: TestClient) -> None:  # noqa: F811
    """Search hits carry eids that get_entity resolves; tree returns nodes."""
    oid = _first_oid(mcp_env)
    hits = _tool(mcp_env, "search_entities", {"oid": oid, "q": "Pizza", "kind": "Class"})
    assert hits["items"]
    eid = hits["items"][0]["eid"]
    ent = _tool(mcp_env, "get_entity", {"oid": oid, "eid": eid})
    assert ent["eid"] == eid
    tree = _tool(mcp_env, "get_class_tree", {"oid": oid})
    assert isinstance(tree, list)


def test_list_ontologies_carries_note(mcp_env: TestClient) -> None:  # noqa: F811
    """list_ontologies attaches agent-facing next-step guidance (A2, in lieu of a manifest).

    The note is MCP-layer only: the REST envelope stays untouched for
    browser/API consumers.
    """
    res = _tool(mcp_env, "list_ontologies", {})
    assert res["items"] and res["total"] >= 1
    assert "search_entities" in res["note"] and "get_ontology" in res["note"]
    # REST stays note-free (loopback philosophy: MCP presentation only).
    r = mcp_env.get("/api/v1/ontologies", headers={"Authorization": f"Bearer {mcp_env.jwt}"})
    assert "note" not in r.json()["data"]


def test_search_envelope_marks_truncation(mcp_env: TestClient) -> None:  # noqa: F811
    """search_entities wraps hits in an envelope that never truncates silently (D9①).

    limitReached=true when the engine broke at limit (more may exist); the note
    tells the agent how to react (matched_field is the per-hit rationale).
    """
    oid = _first_oid(mcp_env)
    res = _tool(mcp_env, "search_entities", {"oid": oid, "q": "e", "limit": 1})
    assert res["limitReached"] is True
    assert res["limit"] == 1 and res["items"]
    assert "matched_field" in res["note"]


def test_sparql_and_lint(mcp_env: TestClient) -> None:  # noqa: F811
    """sparql_query returns the select envelope; run_lint returns its run payload."""
    oid = _first_oid(mcp_env)
    qs = "SELECT ?s WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> } LIMIT 3"
    res = _tool(mcp_env, "sparql_query", {"oid": oid, "qs": qs})
    assert res["truncated"] is False and len(res["rows"]) <= 3
    lint = _tool(mcp_env, "run_lint", {"oid": oid})
    assert "results" in lint


def test_validation_without_shapes_points_to_ui(mcp_env: TestClient) -> None:  # noqa: F811
    """run_validation without shapes is a tool error that points at the web UI."""
    oid = _first_oid(mcp_env)
    msg = _post_rpc(
        mcp_env,
        {
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {"name": "run_validation", "arguments": {"oid": oid}},
        },
        mcp_env.agent_token,
    )
    text = msg["result"]["content"][0]["text"]
    assert msg["result"].get("isError")
    assert "shapes" in text.lower()


def test_export_truncation_contract(
    monkeypatch: pytest.MonkeyPatch,
    mcp_env: TestClient,  # noqa: F811
) -> None:
    """Oversized exports come back flagged, budget-stamped, and with a next-step hint."""
    from ontoworkbench.server.mcp.tools import read

    monkeypatch.setattr(read, "MAX_EXPORT_BYTES", 50)
    oid = _first_oid(mcp_env)
    out = _tool(mcp_env, "export_file", {"oid": oid, "rdf_format": "turtle"})
    assert out["truncated"] is True and out["maxBytes"] == 50
    assert len(out["content"]) <= 50
    assert "sparql_query" in out["hint"]


def test_export_full_under_limit(mcp_env: TestClient) -> None:  # noqa: F811
    """An export under the budget passes through whole, flagged untruncated."""
    oid = _first_oid(mcp_env)
    out = _tool(mcp_env, "export_file", {"oid": oid, "rdf_format": "turtle"})
    assert out["truncated"] is False and out["content"]


def _log_lines(out: str) -> list[dict]:
    """Parse the captured stdout into JSON lines (real pipeline output)."""
    events = []
    for line in out.splitlines():
        try:
            events.append(json.loads(line))
        except ValueError:
            continue
    return events


def test_audit_trail_measures_search(tmp_path, capsys, mcp_env: TestClient) -> None:  # noqa: F811
    """Search audit events carry q/hits/limitReached/zero_hit + request id (B3 telemetry).

    The M2 get_context_pack trigger ("agents chain 6-8 hops") and ontology
    coverage gaps ("what did agents search for and not find") are only
    answerable if the audit trail measures searches — today it logs the
    tool name alone.
    """
    import logging as stdlib_logging

    from ontoworkbench.observability.logging import setup_logging

    before = list(stdlib_logging.getLogger().handlers)
    try:
        setup_logging(tmp_path)
        oid = _first_oid(mcp_env)
        _tool(mcp_env, "search_entities", {"oid": oid, "q": "zzz-nosuchthing"})
        _tool(mcp_env, "search_entities", {"oid": oid, "q": "Pizza", "kind": "Class", "limit": 1})
        for handler in stdlib_logging.getLogger().handlers:
            handler.flush()
        events = [
            e
            for e in _log_lines(capsys.readouterr().out)
            if e.get("event") == "mcp.tool" and e.get("tool") == "search_entities"
        ]
        queries = [e.get("query") for e in events]
        assert "zzz-nosuchthing" in queries and "Pizza" in queries
        miss = next(e for e in events if e.get("query") == "zzz-nosuchthing")
        assert miss["zero_hit"] is True and miss["hits"] == 0
        assert isinstance(miss["request_id"], str) and miss["request_id"]
        hit = next(e for e in events if e.get("query") == "Pizza")
        assert hit["hits"] == 1 and hit["limit_reached"] is True
    finally:
        root = stdlib_logging.getLogger()
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_audit_trail_records_result_sizes(tmp_path, capsys, mcp_env: TestClient) -> None:  # noqa: F811
    """tree/sparql audit events carry result sizes (B3 telemetry)."""
    import logging as stdlib_logging

    from ontoworkbench.observability.logging import setup_logging

    before = list(stdlib_logging.getLogger().handlers)
    try:
        setup_logging(tmp_path)
        oid = _first_oid(mcp_env)
        _tool(mcp_env, "get_class_tree", {"oid": oid})
        qs = "SELECT ?s WHERE { ?s a <http://www.w3.org/2002/07/owl#Class> } LIMIT 3"
        _tool(mcp_env, "sparql_query", {"oid": oid, "qs": qs})
        for handler in stdlib_logging.getLogger().handlers:
            handler.flush()
        events = {
            e.get("tool"): e
            for e in _log_lines(capsys.readouterr().out)
            if e.get("event") == "mcp.tool"
        }
        assert events["get_class_tree"]["nodes"] >= 1
        assert isinstance(events["sparql_query"]["rows"], int)
    finally:
        root = stdlib_logging.getLogger()
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                handler.close()
