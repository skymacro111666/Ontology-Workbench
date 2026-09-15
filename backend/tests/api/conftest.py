"""Shared API test fixtures: authenticated client over a temp sqlite store."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine
from ontoworkbench.server.app import create_app
from ontoworkbench.server.autosave import AutosaveManager


def build_app(tmp_path: Path) -> FastAPI:
    """App whose db, data dir and fake SPA dist live under tmp_path."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    # A minimal fake SPA dist so every test exercises the mounted app shape.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html><body>ow-spa-marker</body></html>")
    (dist / "assets" / "app.js").write_text("console.log('ow')")
    return create_app(
        Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "data_dir": tmp_path}),
        spa_dist=dist,
    )


def auth(client: TestClient) -> None:
    """Create the admin account and arm the client's bearer token."""
    client.post("/api/v1/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = client.post("/api/v1/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    client.headers["Authorization"] = f"Bearer {r.json()['data']['token']}"


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Authenticated admin client; app data lives under tmp_path."""
    c = TestClient(build_app(tmp_path))
    auth(c)
    return c


@pytest.fixture()
def autosave_debounce_50ms(client: TestClient) -> Iterator[AutosaveManager]:
    """Swap in a fast autosave (50ms debounce + retries) for mutation tests.

    Teardown flushes every pending saver synchronously: the file lands, no
    timer or writer thread outlives the test, and later tests never see a
    stray save from this one.
    """
    fast = AutosaveManager(debounce_s=0.05, retry_base=0.05)
    old = client.app.state.autosave
    client.app.state.autosave = fast
    yield fast
    fast.flush_all()
    client.app.state.autosave = old
