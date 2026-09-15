"""MCP mount: conditional on tokens, gated by credential, JSON-RPC reachable."""

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import build_app


def _rpc_response(r) -> dict:
    """Parse a JSON-RPC reply that may be JSON or an SSE data line."""
    assert r.status_code == 200, (r.status_code, r.text[:300])
    if r.headers.get("content-type", "").startswith("text/event-stream"):
        msg = None
        for line in r.text.splitlines():
            if line.startswith("data:"):
                candidate = json.loads(line[5:].strip())
                if candidate.get("id") is not None:
                    msg = candidate
        assert msg is not None, r.text[:300]
        return msg
    return r.json()


def _post_rpc(client: TestClient, body: dict, token: str | None) -> dict:
    """POST one JSON-RPC message with the given bearer token."""
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return _rpc_response(client.post("/api/v1/mcp/", json=body, headers=headers))


def _tools_call(client: TestClient, token: str, name: str, arguments: dict | None = None) -> dict:
    """POST a tools/call request for one tool."""
    return _post_rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        },
        token,
    )


@pytest.fixture()
def mcp_env(tmp_path: Path) -> Iterator[TestClient]:
    """App with one seeded agent token — the mount exists; token on the client.

    Two app builds over the same DB: the first mints the token over REST, the
    second sees count_any() > 0 and mounts. c2 is a context-manager client —
    the MCP lifespan must run or every request dies "Task group is not
    initialized". The client-level Authorization exists only for the sample
    load; afterwards it is removed so gate tests can send no credential.
    """
    c1 = TestClient(build_app(tmp_path))
    c1.post("/api/v1/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = c1.post("/api/v1/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    c1.jwt = r.json()["data"]["token"]
    c1.headers["Authorization"] = f"Bearer {c1.jwt}"
    tok = c1.post("/api/v1/agent-tokens", json={"label": "claude"}).json()["data"]["token"]
    with TestClient(build_app(tmp_path)) as c2:  # same DB, now 1 token -> mounted
        c2.jwt, c2.agent_token = c1.jwt, tok
        c2.headers["Authorization"] = f"Bearer {c1.jwt}"
        c2.post("/api/v1/samples/pizza")
        del c2.headers["Authorization"]
        yield c2


def test_zero_tokens_means_no_route(tmp_path: Path) -> None:
    """No agent tokens in the DB means the MCP route does not exist."""
    c = TestClient(build_app(tmp_path))
    r = c.post("/api/v1/mcp/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 404


def test_gate_rejects_missing_and_bad_tokens(mcp_env: TestClient) -> None:
    """Requests without a bearer, or with an unknown one, die 401."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert mcp_env.post("/api/v1/mcp/", json=body).status_code == 401
    r = mcp_env.post("/api/v1/mcp/", json=body, headers={"Authorization": "Bearer owag_wrong"})
    assert r.status_code == 401


def test_human_jwt_can_debug(mcp_env: TestClient) -> None:
    """A human JWT passes the gate (debug path)."""
    msg = _post_rpc(mcp_env, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, mcp_env.jwt)
    assert "result" in msg


def test_list_ontologies_tool(mcp_env: TestClient) -> None:
    """tools/call list_ontologies returns the pizza sample among the items."""
    msg = _tools_call(mcp_env, mcp_env.agent_token, "list_ontologies")
    assert not msg["result"].get("isError")
    payload = json.loads(msg["result"]["content"][0]["text"])
    assert any(o.get("id") for o in payload["items"])


def test_unknown_oid_gets_pointing_error(mcp_env: TestClient) -> None:
    """An unknown oid yields a tool error that points at list_ontologies."""
    msg = _tools_call(
        mcp_env,
        mcp_env.agent_token,
        "get_ontology",
        {"oid": "00000000-0000-0000-0000-000000000000"},
    )
    text = msg["result"]["content"][0]["text"]
    assert msg["result"].get("isError") or "Error" in text
    assert "list_ontologies" in text
