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


# --- R2RML P2: gated save + swap rollback ---------------------------------


def _row(oid: str):
    """The r2rml row for an ontology, straight from the DB."""
    from uuid import UUID

    from sqlalchemy import select

    from ontoworkbench.db.models import OntologyR2rml
    from ontoworkbench.db.session import sessionmaker_or_fail

    with sessionmaker_or_fail()() as s:
        return s.scalar(select(OntologyR2rml).where(OntologyR2rml.ontology_id == UUID(oid)))


def _edited(client: TestClient, oid: str, content: str, base_hash: str):
    return client.put(
        f"/api/v1/ontologies/{oid}/r2rml", json={"content": content, "baseHash": base_hash}
    )


def test_get_r2rml_carries_hash_and_previous(client: TestClient, shop_db: Path) -> None:
    """GET now carries contentHash (64 hex) and previousExists (false at first)."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    d = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    assert len(d["contentHash"]) == 64
    assert d["previousExists"] is False


def test_put_r2rml_saves_verbatim_and_sets_previous(client: TestClient, shop_db: Path) -> None:
    """PUT writes the submitted bytes verbatim; previous_ttl holds the old text."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    d = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    edited = d["content"] + "\n# hand edit\n"
    r = _edited(client, oid, edited, d["contentHash"])
    assert r.status_code == 200
    assert r.json()["data"]["content"] == edited
    assert r.json()["data"]["previousExists"] is True
    row = _row(oid)
    assert Path(row.storage_path).read_bytes() == edited.encode()  # 逐字节,无重序列化
    assert row.previous_ttl == d["content"]  # 旧版入槽


def test_put_r2rml_422_lists_findings(client: TestClient, shop_db: Path) -> None:
    """A typo'd column 422s R2RML_INVALID; the hint lists findings + columns."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    d = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    bad = d["content"].replace('rr:column "name"', 'rr:column "nme"')
    r = _edited(client, oid, bad, d["contentHash"])
    assert r.status_code == 422
    env = r.json()
    assert env["code"] == "R2RML_INVALID"
    assert "id、name" in env["hint"]
    assert "L3" in env["hint"]


def test_put_r2rml_409_leaves_file_untouched(client: TestClient, shop_db: Path) -> None:
    """A stale baseHash 409s R2RML_STALE; file and previous_ttl stay put."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    d = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    r = _edited(client, oid, d["content"] + "x", "0" * 64)
    assert r.status_code == 409
    assert r.json()["code"] == "R2RML_STALE"
    assert _row(oid).previous_ttl is None
    d2 = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    assert d2["contentHash"] == d["contentHash"]


def test_rollback_swaps_and_redoes(client: TestClient, shop_db: Path) -> None:
    """Rollback swaps: once → old text; twice → the edit again (redo)."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    d = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    edited = d["content"] + "\n# hand edit\n"
    _edited(client, oid, edited, d["contentHash"])
    h = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]["contentHash"]
    r = client.post(f"/api/v1/ontologies/{oid}/r2rml/rollback", json={"baseHash": h})
    assert r.status_code == 200
    assert r.json()["data"]["content"] == d["content"]  # 回到旧文
    h2 = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]["contentHash"]
    r2 = client.post(f"/api/v1/ontologies/{oid}/r2rml/rollback", json={"baseHash": h2})
    assert r2.status_code == 200
    assert r2.json()["data"]["content"] == edited  # 再回退=redo


def test_rollback_404_when_no_previous(client: TestClient, shop_db: Path) -> None:
    """Rolling back a first version (no previous) 404s R2RML_NO_PREVIOUS."""
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    h = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]["contentHash"]
    r = client.post(f"/api/v1/ontologies/{oid}/r2rml/rollback", json={"baseHash": h})
    assert r.status_code == 404
    assert r.json()["code"] == "R2RML_NO_PREVIOUS"


# --- final-review fixes: incomplete-shape 422 + size cap --------------------


def test_put_r2rml_incomplete_shape_422_even_without_snapshot(
    client: TestClient, shop_db: Path
) -> None:
    """存量行(schema_json NULL)+ 残缺形状:422 带定位而非 500;盘上文件不动."""
    from uuid import UUID

    from sqlalchemy import select

    from ontoworkbench.db.models import OntologyR2rml
    from ontoworkbench.db.session import sessionmaker_or_fail

    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    with sessionmaker_or_fail()() as s:
        row = s.scalar(select(OntologyR2rml).where(OntologyR2rml.ontology_id == UUID(oid)))
        row.schema_json = None  # P1 存量行:无快照
        s.commit()
    d = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    incomplete = (
        "@prefix rr: <http://www.w3.org/ns/r2rml#> .\n"
        "<https://local/shop/r2rml/Customer> a rr:TriplesMap ;\n"
        '    rr:logicalTable [ rr:tableName "customer" ] .\n'
    )
    r = _edited(client, oid, incomplete, d["contentHash"])
    assert r.status_code == 422
    assert r.json()["code"] == "R2RML_INVALID"
    assert "残缺" in (r.json()["hint"] or "")
    # 门挡下后 GET 仍可用(不写盘、不砖死)
    d2 = client.get(f"/api/v1/ontologies/{oid}/r2rml").json()["data"]
    assert d2["content"] == d["content"] and d2["contentHash"] == d["contentHash"]


def test_put_r2rml_rejects_oversize(
    client: TestClient, shop_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PUT 内容超上限 413,与 PUT /source 同门(MCP/P4 暴露面前先收口)."""
    from ontoworkbench.server.routers import ontologies as ontologies_router

    monkeypatch.setattr(ontologies_router, "MAX_UPLOAD", 10)
    oid = _imported(client, shop_db, generate_r2rml=True)["ontologyId"]
    r = client.put(f"/api/v1/ontologies/{oid}/r2rml", json={"content": "x" * 11, "baseHash": "z"})
    assert r.status_code == 413
    assert r.json()["code"] == "UPLOAD_TOO_LARGE"
