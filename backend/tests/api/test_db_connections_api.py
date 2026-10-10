"""db-connections endpoints: CRUD shapes, ciphertext at rest, engines list."""

from fastapi.testclient import TestClient
from sqlalchemy import select

from ontoworkbench.db.models import DbConnection
from ontoworkbench.db.session import sessionmaker_or_fail

CONN_BODY = {
    "name": "pg1",
    "dbType": "postgres",
    "host": "h",
    "port": 5432,
    "database": "app",
    "username": "u",
    "password": "plain-pw",
}


def test_create_encrypts_password_at_rest(client: TestClient) -> None:
    """The stored column holds Fernet ciphertext, never the plaintext."""
    r = client.post("/api/v1/db-connections", json=CONN_BODY)
    assert r.status_code == 201
    with sessionmaker_or_fail()() as s:
        row = s.scalars(select(DbConnection)).one()
        assert row.password_cipher != "plain-pw" and "plain-pw" not in row.password_cipher


def test_list_never_returns_password(client: TestClient) -> None:
    """List payloads carry no password material under any key spelling."""
    client.post("/api/v1/db-connections", json=CONN_BODY)
    body = client.get("/api/v1/db-connections").text
    assert "plain-pw" not in body
    assert "passwordCipher" not in body and "password_cipher" not in body


def test_duplicate_name_422(client: TestClient) -> None:
    """A second connection with the same name is rejected."""
    client.post("/api/v1/db-connections", json=CONN_BODY)
    assert client.post("/api/v1/db-connections", json=CONN_BODY).status_code == 422


def test_unknown_engine_422(client: TestClient) -> None:
    """DbType outside the registry is rejected."""
    bad = dict(CONN_BODY, name="x", dbType="oracle")
    assert client.post("/api/v1/db-connections", json=bad).status_code == 422


def test_put_omitted_password_keeps_cipher(client: TestClient) -> None:
    """PUT without password keeps the stored ciphertext."""
    cid = client.post("/api/v1/db-connections", json=CONN_BODY).json()["data"]["id"]
    r = client.put(f"/api/v1/db-connections/{cid}", json={"host": "h2"})
    assert r.status_code == 200
    with sessionmaker_or_fail()() as s:
        row = s.scalars(select(DbConnection)).one()
        assert row.host == "h2" and row.password_cipher != "plain-pw"


def test_delete_owned(client: TestClient) -> None:
    """Delete removes the row; a second delete 404s."""
    cid = client.post("/api/v1/db-connections", json=CONN_BODY).json()["data"]["id"]
    assert client.delete(f"/api/v1/db-connections/{cid}").status_code == 200
    assert client.delete(f"/api/v1/db-connections/{cid}").status_code == 404
    assert client.get("/api/v1/db-connections").json()["data"] == []


def test_engines_lists_installed_flags(client: TestClient) -> None:
    """All three engines list; uninstalled extras are flagged."""
    import importlib.util

    data = client.get("/api/v1/db-connections/engines").json()["data"]
    by = {e["dbType"]: e for e in data}
    assert set(by) == {"postgres", "mysql", "sqlite"}
    assert by["sqlite"]["installed"] is True
    assert by["postgres"]["installed"] is (importlib.util.find_spec("psycopg") is not None)


def test_engines_carry_default_ports(client: TestClient) -> None:
    """The registry's default port rides along for form prefill; sqlite has none."""
    data = client.get("/api/v1/db-connections/engines").json()["data"]
    by = {e["dbType"]: e for e in data}
    assert by["postgres"]["defaultPort"] == 5432
    assert by["mysql"]["defaultPort"] == 3306
    assert by["sqlite"]["defaultPort"] is None


def test_test_endpoint_bad_path_fails_cleanly(client: TestClient) -> None:
    """A connect test against a nonexistent sqlite dir fails on the OK envelope."""
    r = client.post(
        "/api/v1/db-connections/test",
        json={"dbType": "sqlite", "database": "/nonexistent-dir/x.db"},
    )
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is False
