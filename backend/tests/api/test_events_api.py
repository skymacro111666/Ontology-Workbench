"""Registry read API: envelope shape, ownership, query validation (Phase 1)."""

from pathlib import Path

from fastapi.testclient import TestClient

from ontoworkbench.auth.password import hash_password
from ontoworkbench.db.repositories import UserRepository
from ontoworkbench.db.session import sessionmaker_or_fail
from tests.api.conftest import build_app
from tests.api.test_browse_api import _upload


def test_events_empty_list(client: TestClient) -> None:
    """A fresh ontology serves an empty journal page."""
    oid = _upload(client)
    r = client.get(f"/api/v1/ontologies/{oid}/events")
    assert r.status_code == 200
    body = r.json()["data"]
    assert body == {"items": [], "nextBeforeId": None}


def test_events_unknown_oid_404(client: TestClient) -> None:
    """Unknown oids (and non-uuid garbage) share the standard 404."""
    assert (
        client.get("/api/v1/ontologies/00000000-0000-0000-0000-000000000009/events").status_code
        == 404
    )
    assert client.get("/api/v1/ontologies/not-a-uuid/events").status_code == 404


def test_events_limit_validation(client: TestClient) -> None:
    """Limit is clamped to 1..200; outside values 422."""
    oid = _upload(client)
    assert client.get(f"/api/v1/ontologies/{oid}/events?limit=0").status_code == 422
    assert client.get(f"/api/v1/ontologies/{oid}/events?limit=201").status_code == 422


def test_events_other_user_404(tmp_path: Path) -> None:
    """A second user in the same DB cannot read another's journal (404, no leak)."""
    from tests.api.conftest import auth

    app = build_app(tmp_path)
    owner = TestClient(app)
    auth(owner)
    oid = _upload(owner)

    with sessionmaker_or_fail()() as s:
        UserRepository(s).create("mallory", hash_password("long-enough-pw"))
        s.commit()

    other = TestClient(app)
    r = other.post("/api/v1/auth/login", json={"username": "mallory", "password": "long-enough-pw"})
    other.headers["Authorization"] = f"Bearer {r.json()['data']['token']}"
    assert other.get(f"/api/v1/ontologies/{oid}/events").status_code == 404
