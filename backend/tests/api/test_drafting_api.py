"""Drafting endpoints: schema reflect, generate job, agent import."""

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.structured import parse_json_block
from ontoworkbench.core.ai.types import ModelResponse
from ontoworkbench.server.routers.ai_settings import get_ai_provider

AI_ENV = ("AI_MODEL_PROVIDER", "AI_BASE_URL", "AI_API_KEY", "AI_MODEL")

DECISIONS = (
    '```json\n{"classes": [{"name": "Customer", "label": "客户", "comment": null, '
    '"sourceTable": "customer", "parentName": null}, '
    '{"name": "Order", "label": "订单", "comment": null, '
    '"sourceTable": "orders", "parentName": "Customer"}], '
    '"objectProperties": [], '
    '"dataProperties": [{"name": "name", "label": null, "domain": "Customer", '
    '"datatype": "xsd:string", "sourceColumn": "customer.name"}]}\n```'
)
DECISIONS_OBJ = parse_json_block(DECISIONS)


def _make_db(path: Path) -> None:
    """Task 12's DDL shape: customer + orders with one FK edge."""
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE customer (id INTEGER PRIMARY KEY, name VARCHAR(80));
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customer(id)
        );
        """
    )
    con.commit()
    con.close()


@pytest.fixture()
def shop_db(tmp_path: Path) -> Path:
    """A reflected-source sqlite file named after its database."""
    db = tmp_path / "shop.db"
    _make_db(db)
    return db


def _reflected(client: TestClient, db: Path) -> dict:
    """POST drafting/schema by raw values; return the wire schema."""
    r = client.post(
        "/api/v1/ontologies/drafting/schema",
        json={"dbType": "sqlite", "database": str(db)},
    )
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["tableCount"] == len(data["schema"]["tables"])
    return data["schema"]


def test_schema_endpoint_reflects_sqlite(client: TestClient, shop_db: Path) -> None:
    """Raw-values reflect: both tables, the FK edge, sqlite_ tables skipped."""
    schema = _reflected(client, shop_db)
    assert schema["databaseName"] == "shop"
    names = {t["name"] for t in schema["tables"]}
    assert names == {"customer", "orders"}
    orders = next(t for t in schema["tables"] if t["name"] == "orders")
    assert orders["foreignKeys"] == [
        {"column": "customer_id", "refTable": "customer", "refColumn": "id"}
    ]


def test_schema_by_saved_connection(client: TestClient, shop_db: Path) -> None:
    """ConnectionId path: saved profile decrypts into the same reflection."""
    r = client.post(
        "/api/v1/db-connections",
        json={"name": "shop", "dbType": "sqlite", "database": str(shop_db)},
    )
    assert r.status_code == 201
    cid = r.json()["data"]["id"]
    r = client.post("/api/v1/ontologies/drafting/schema", json={"connectionId": cid})
    assert r.status_code == 200
    schema = r.json()["data"]["schema"]
    assert {t["name"] for t in schema["tables"]} == {"customer", "orders"}


def test_generate_job_polls_to_done(client: TestClient, shop_db: Path) -> None:
    """Generate runs as a job; polling reaches done with TTL + stats."""
    client.app.dependency_overrides[get_ai_provider] = lambda: FakeProvider(
        [ModelResponse(text=DECISIONS, in_tokens=10, out_tokens=5)]
    )
    try:
        r = client.post(
            "/api/v1/ontologies/drafting/generate", json={"schema": _reflected(client, shop_db)}
        )
        assert r.status_code == 202
        job_id = r.json()["data"]["jobId"]
    finally:
        client.app.dependency_overrides.clear()
    d = None
    for _ in range(200):
        d = client.get(f"/api/v1/ontologies/drafting/jobs/{job_id}").json()["data"]
        if d["status"] != "running":
            break
        time.sleep(0.05)
    assert d is not None and d["status"] == "done"
    assert "shop:Customer a owl:Class" in d["result"]["ttl"]
    assert d["batchCount"] == 1
    assert d["result"]["stats"]["classCount"] == 2
    # FK completion: orders.customer_id was uncovered by the LLM
    assert any(op["name"] == "hasCustomer" for op in d["result"]["decisions"]["objectProperties"])


def test_generate_without_ai_configured_503(
    client: TestClient, shop_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No env, no DB row → 503 AI_NOT_CONFIGURED before any job exists."""
    for var in AI_ENV:
        monkeypatch.delenv(var, raising=False)
    r = client.post(
        "/api/v1/ontologies/drafting/generate", json={"schema": _reflected(client, shop_db)}
    )
    assert r.status_code == 503
    assert r.json()["code"] == "AI_NOT_CONFIGURED"


def test_import_creates_agent_ontology(client: TestClient, shop_db: Path) -> None:
    """Import lands an agent-sourced ontology with an agent-origin journal row."""
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json={
            "schema": _reflected(client, shop_db),
            "decisions": DECISIONS_OBJ,
            "rejectedClassNames": [],
            "namespace": "https://local/shop#",
        },
    )
    assert r.status_code == 201
    data = r.json()["data"]
    oid = data["ontologyId"]
    assert data["title"]
    meta = client.get(f"/api/v1/ontologies/{oid}/meta").json()["data"]
    assert meta["source"] == "agent"
    events = client.get(f"/api/v1/ontologies/{oid}/events").json()["data"]
    assert events["items"][0]["origin"] == "agent"


def test_import_rejection_cascades(client: TestClient, shop_db: Path) -> None:
    """Rejecting Customer drops its data property and the hasCustomer edge."""
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json={
            "schema": _reflected(client, shop_db),
            "decisions": DECISIONS_OBJ,
            "rejectedClassNames": ["Customer"],
            "namespace": "https://local/shop#",
        },
    )
    assert r.status_code == 201
    oid = r.json()["data"]["ontologyId"]
    src = client.get(f"/api/v1/ontologies/{oid}/export/file", params={"format": "turtle"}).json()[
        "data"
    ]["content"]
    assert "shop:Customer" not in src
    assert "hasCustomer" not in src
    assert "shop:Order" in src  # the survivor stays
