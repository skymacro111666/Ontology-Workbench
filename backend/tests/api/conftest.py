"""Shared API test fixtures: authenticated client over a temp sqlite store."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.config import Settings
from ontoworkbench.db.models import Base
from ontoworkbench.db.session import init_engine
from ontoworkbench.server.app import create_app


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """Authenticated admin client; app data lives under tmp_path."""
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = init_engine(db_url)
    Base.metadata.create_all(engine)
    app = create_app(
        Settings.load({"jwt_secret": "t" * 32, "db_url": db_url, "data_dir": tmp_path})
    )
    c = TestClient(app)
    c.post("/api/auth/setup", json={"username": "admin", "password": "long-enough-pw"})
    r = c.post("/api/auth/login", json={"username": "admin", "password": "long-enough-pw"})
    c.headers["Authorization"] = f"Bearer {r.json()['data']['token']}"
    return c
