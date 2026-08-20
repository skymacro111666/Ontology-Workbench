"""setup -> login -> me flow, including one-shot setup."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine
from ontoworkbench.server.app import create_app

FIVE_FIELDS = {"code", "message", "data", "hint", "request_id"}


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """App + engine over a file-backed sqlite (visible across request threads)."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    app = create_app(Settings.load({"jwt_secret": "t" * 32, "db_url": db_url}))
    return TestClient(app)


def test_setup_login_me(client: TestClient) -> None:
    """One-shot setup, login issues a token, me echoes the user."""
    r = client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    assert r.json()["code"] == "OK"
    assert set(r.json()) == FIVE_FIELDS

    # valid-format creds: reaches the handler, which reports one-shot setup done
    again = client.post("/api/auth/setup", json={"username": "bob", "password": "long-enough-pw"})
    assert again.json()["code"] == "SETUP_DONE"

    login = client.post("/api/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    assert login.json()["code"] == "OK"
    assert set(login.json()) == FIVE_FIELDS
    token = login.json()["data"]["token"]

    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["data"]["username"] == "admin"
    bad = client.get("/api/auth/me")
    assert bad.json()["code"] == "AUTH_REQUIRED"
    assert bad.json()["data"] is None


def test_login_rejects_wrong_password(client: TestClient) -> None:
    """Wrong password yields AUTH_INVALID_CREDENTIALS, not a token."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert r.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_login_rejects_unknown_user(client: TestClient) -> None:
    """Unknown username runs the dummy-hash path and yields the same error."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = client.post("/api/auth/login", json={"username": "ghost", "password": "wrong-password"})
    assert r.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_me_rejects_garbage_token(client: TestClient) -> None:
    """A malformed token is TOKEN_EXPIRED (invalid or expired), not a 500."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.json()["code"] == "TOKEN_EXPIRED"
