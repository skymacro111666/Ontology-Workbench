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


def test_status_needs_no_auth_and_flips_after_setup(client: TestClient) -> None:
    """GET /api/auth/status is auth-free and reports pending first-run setup."""
    fresh = client.get("/api/auth/status")
    assert fresh.json()["code"] == "OK"
    assert fresh.json()["data"] == {"need_setup": True}

    client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    done = client.get("/api/auth/status")
    assert done.json()["code"] == "OK"
    assert done.json()["data"] == {"need_setup": False}


def _login_token(client: TestClient, password: str) -> str:
    """Log in as the (already set up) admin and return the bearer token."""
    r = client.post("/api/auth/login", json={"username": "admin", "password": password})
    return r.json()["data"]["token"]


def test_change_password_round_trip(client: TestClient) -> None:
    """Wrong current password rejected; a correct change swaps login credentials.

    Issued tokens stay valid after the change (keep-logged-in design).
    """
    client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    token = _login_token(client, "long-enough-pw")
    auth = {"Authorization": f"Bearer {token}"}

    bad = client.put(
        "/api/auth/password",
        json={"currentPassword": "wrong-password", "newPassword": "brand-new-long-pw"},
        headers=auth,
    )
    assert bad.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    # Rejected change leaves the old password working.
    assert _login_token(client, "long-enough-pw")

    ok = client.put(
        "/api/auth/password",
        json={"currentPassword": "long-enough-pw", "newPassword": "brand-new-long-pw"},
        headers=auth,
    )
    assert ok.json()["code"] == "OK"
    assert set(ok.json()) == FIVE_FIELDS

    old = client.post("/api/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    assert old.json()["code"] == "AUTH_INVALID_CREDENTIALS"
    assert _login_token(client, "brand-new-long-pw")
    # The token issued before the change still authenticates.
    me = client.get("/api/auth/me", headers=auth)
    assert me.json()["data"]["username"] == "admin"


def test_change_password_requires_auth_and_length(client: TestClient) -> None:
    """Unauthenticated calls bounce; short new passwords fail validation."""
    client.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    anon = client.put(
        "/api/auth/password",
        json={"currentPassword": "long-enough-pw", "newPassword": "brand-new-long-pw"},
    )
    assert anon.json()["code"] == "AUTH_REQUIRED"

    token = _login_token(client, "long-enough-pw")
    short = client.put(
        "/api/auth/password",
        json={"currentPassword": "long-enough-pw", "newPassword": "short"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert short.json()["code"] == "VALIDATION_ERROR"
