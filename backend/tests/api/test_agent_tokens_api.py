"""agent-tokens management endpoints (spec D12): one-time plaintext, prefix-only listing."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ontoworkbench.db.models import AgentToken
from ontoworkbench.db.session import sessionmaker_or_fail


@pytest.fixture()
def seeded(client: TestClient) -> TestClient:
    """Admin client with one minted token stashed as ``client.token``."""
    r = client.post("/api/v1/agent-tokens", json={"label": "claude"})
    assert r.status_code == 201
    client.token = r.json()["data"]["token"]
    return client


def test_create_returns_owag_plaintext_once(seeded: TestClient) -> None:
    """Create returns the owag_ plaintext once; the row stores hash + prefix only."""
    assert seeded.token.startswith("owag_")
    with sessionmaker_or_fail()() as session:
        rows = session.scalars(select(AgentToken)).all()
        assert len(rows) == 1
        assert rows[0].token_hash != seeded.token  # hash only, never plaintext
        assert rows[0].token_prefix == seeded.token[:8]


def test_list_shows_prefix_never_secret(seeded: TestClient) -> None:
    """Listing shows label + tokenPrefix; neither plaintext nor hash appears."""
    r = seeded.get("/api/v1/agent-tokens")
    item = r.json()["data"][0]
    assert item["label"] == "claude" and item["tokenPrefix"].startswith("owag_")
    body = r.text
    assert seeded.token not in body and rows_have_no_hash(body)


def rows_have_no_hash(body: str) -> bool:
    """Neither snake_case nor camelCase hash key may appear in a response body."""
    return "token_hash" not in body and "tokenHash" not in body


def test_duplicate_label_422(seeded: TestClient) -> None:
    """A second token with the same label is rejected with 422."""
    assert seeded.post("/api/v1/agent-tokens", json={"label": "claude"}).status_code == 422


def test_revoke_is_immediate(seeded: TestClient) -> None:
    """Hard delete: the very next request with the token is 401."""
    tid = seeded.get("/api/v1/agent-tokens").json()["data"][0]["id"]
    assert seeded.delete(f"/api/v1/agent-tokens/{tid}").status_code == 200
    r = seeded.get("/api/v1/ontologies", headers={"Authorization": f"Bearer {seeded.token}"})
    assert r.status_code == 401


def test_machine_credential_cannot_manage(seeded: TestClient) -> None:
    """An owag_ token cannot mint or list tokens (allowlist 403)."""
    h = {"Authorization": f"Bearer {seeded.token}"}
    assert seeded.post("/api/v1/agent-tokens", headers=h, json={"label": "x"}).status_code == 403
    assert seeded.get("/api/v1/agent-tokens", headers=h).status_code == 403


def test_label_validation(client: TestClient) -> None:
    """Labels must be 1-64 chars of [A-Za-z0-9._-]; empty/spacey labels are 422."""
    assert client.post("/api/v1/agent-tokens", json={"label": ""}).status_code == 422
    assert client.post("/api/v1/agent-tokens", json={"label": "not valid!"}).status_code == 422
