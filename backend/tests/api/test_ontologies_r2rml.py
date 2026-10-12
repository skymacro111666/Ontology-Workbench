"""R2RML read endpoints: envelope view + binary download."""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ontoworkbench.core.ai.structured import parse_json_block

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


@pytest.fixture()
def shop_db(tmp_path: Path) -> Path:
    """A reflected-source sqlite file (same DDL shape as the drafting tests)."""
    db = tmp_path / "shop.db"
    con = sqlite3.connect(db)
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
    return db


def _reflected(client: TestClient, db: Path) -> dict:
    """POST drafting/schema by raw values; return the wire schema."""
    r = client.post(
        "/api/v1/ontologies/drafting/schema", json={"dbType": "sqlite", "database": str(db)}
    )
    assert r.status_code == 200
    return r.json()["data"]["schema"]


def _imported(client: TestClient, shop_db: Path, generate_r2rml: bool) -> dict:
    """Import the fixture decisions; optionally ask for the R2RML companion."""
    body = {
        "schema": _reflected(client, shop_db),
        "decisions": DECISIONS_OBJ,
        "rejectedClassNames": [],
        "namespace": "https://local/shop#",
        "filename": "shop.ttl",
        "labelLanguage": "zh",
    }
    if generate_r2rml:
        body["generateR2rml"] = True
    r = client.post("/api/v1/ontologies/drafting/import", json=body)
    assert r.status_code == 201
    return r.json()["data"]


def test_get_r2rml_returns_structure_and_content(client: TestClient, shop_db: Path) -> None:
    """The view endpoint returns metadata, Turtle and the parsed structure."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    r = client.get(f"/api/v1/ontologies/{oid}/r2rml")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["filename"] == "shop.r2rml.ttl"
    assert "rr:TriplesMap" in d["content"]
    assert d["structure"][0]["table"] == "customer"
    assert d["skippedTables"] == []


def test_get_r2rml_404_when_absent(client: TestClient, shop_db: Path) -> None:
    """An ontology imported without the companion answers plain 404."""
    oid = _imported(client, shop_db, generate_r2rml=False)["ontologyId"]
    r = client.get(f"/api/v1/ontologies/{oid}/r2rml")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


def test_download_streams_turtle(client: TestClient, shop_db: Path) -> None:
    """The download endpoint streams the file outside the JSON envelope."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    r = client.get(f"/api/v1/ontologies/{oid}/r2rml/download")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/turtle")
    assert b"rr:TriplesMap" in r.content
