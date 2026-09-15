"""Agent token as a first-class REST credential: allowlist + attribution (spec D10/D11)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.auth import agent_tokens
from ontoworkbench.db.repositories import AgentTokenRepository, UserRepository
from ontoworkbench.db.session import sessionmaker_or_fail
from tests.api.conftest import build_app


@pytest.fixture()
def agent(tmp_path: Path) -> TestClient:
    """Admin client plus a seeded agent token stashed on the client object."""
    c = TestClient(build_app(tmp_path))
    c.post("/api/v1/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = c.post("/api/v1/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    jwt = r.json()["data"]["token"]
    with sessionmaker_or_fail()() as session:
        u = UserRepository(session).first()
        token = agent_tokens.mint()
        AgentTokenRepository(session).create(
            u.id, "claude", agent_tokens.hash_token(token), token[:8]
        )
        session.commit()
    # Load the sample as the human (JWT): the agent allowlist has no POST for it.
    c.headers["Authorization"] = f"Bearer {jwt}"
    c.post("/api/v1/samples/pizza")
    c.jwt, c.agent_token = jwt, token
    return c


def _oid(client: TestClient) -> str:
    return client.get("/api/v1/ontologies").json()["data"]["items"][0]["id"]


def test_agent_reads_allowlisted_endpoints(agent: TestClient) -> None:
    """Agent token reaches every endpoint in the allowlist with 200s."""
    h = {"Authorization": f"Bearer {agent.agent_token}"}
    assert agent.get("/api/v1/ontologies", headers=h).status_code == 200
    oid = _oid(agent)
    assert agent.get(f"/api/v1/ontologies/{oid}/meta", headers=h).status_code == 200
    r = agent.post(
        f"/api/v1/ontologies/{oid}/query",
        headers=h,
        json={"qs": "SELECT * WHERE { ?s ?p ?o } LIMIT 1"},
    )
    assert r.status_code == 200


def test_agent_blocked_outside_allowlist(agent: TestClient) -> None:
    """Anything off the allowlist is a 403, whatever the method."""
    h = {"Authorization": f"Bearer {agent.agent_token}"}
    oid = _oid(agent)
    assert agent.get("/api/v1/auth/me", headers=h).status_code == 403
    # POST outside the allowlist; /api/v1/agent-tokens itself lands in Task 6.
    r = agent.post(
        f"/api/v1/ontologies/{oid}/query/export",
        headers=h,
        json={"qs": "SELECT * WHERE { ?s ?p ?o } LIMIT 1", "format": "csv"},
    )
    assert r.status_code == 403
    assert (
        agent.put(f"/api/v1/ontologies/{oid}/layout", headers=h, json={"positions": {}}).status_code
        == 403
    )
    assert agent.get(f"/api/v1/ontologies/{oid}/source", headers=h).status_code == 403


def test_agent_403_code_is_envelope_agent_forbidden(agent: TestClient) -> None:
    """The 403 body carries the machine-readable AGENT_FORBIDDEN code."""
    r = agent.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {agent.agent_token}"})
    assert r.json()["code"] == "AGENT_FORBIDDEN"


def test_unknown_owag_token_is_401(agent: TestClient) -> None:
    """An owag_-shaped token that resolves to nothing is a plain 401."""
    r = agent.get("/api/v1/ontologies", headers={"Authorization": "Bearer owag_unknown"})
    assert r.status_code == 401


def test_owner_isolation_agent_sees_own_ontologies(agent: TestClient) -> None:
    """The agent acts as its bound account: it sees that account's ontologies."""
    # The token is bound to the admin account; its owner has pizza loaded.
    r = agent.get("/api/v1/ontologies", headers={"Authorization": f"Bearer {agent.agent_token}"})
    assert len(r.json()["data"]["items"]) >= 1
