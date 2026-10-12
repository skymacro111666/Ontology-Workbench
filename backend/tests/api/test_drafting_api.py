"""Drafting endpoints: schema reflect, generate job, agent import."""

import asyncio
import sqlite3
import time
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.structured import parse_json_block
from ontoworkbench.core.ai.types import ModelResponse
from ontoworkbench.core.drafting.models import ColumnSpec, SchemaModel, TableSpec
from ontoworkbench.core.drafting.r2rml import schema_hash
from ontoworkbench.core.errors import CoreError
from ontoworkbench.db.models import OntologyR2rml
from ontoworkbench.db.session import sessionmaker_or_fail
from ontoworkbench.server.routers import drafting as drafting_router
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


def _r2rml_row(oid: str) -> OntologyR2rml | None:
    """The companion row for an ontology, straight from the DB."""
    with sessionmaker_or_fail()() as s:
        return s.scalar(select(OntologyR2rml).where(OntologyR2rml.ontology_id == UUID(oid)))


def test_import_with_generate_r2rml_lands_file_and_row(client: TestClient, shop_db: Path) -> None:
    """generateR2rml lands file and row.

    The DB row carries the P3 drift inputs (namespace, schema hash, base
    revision).
    """
    payload = _imported(client, shop_db, generate_r2rml=True)
    assert payload["r2rml"]["filename"] == "shop.r2rml.ttl"
    assert payload["r2rml"]["skippedTables"] == []
    row = _r2rml_row(payload["ontologyId"])
    assert row is not None
    assert row.namespace == "https://local/shop#"
    assert len(row.schema_hash) == 64
    assert row.base_revision >= 0
    p = Path(row.storage_path)
    assert p.exists() and p.name == "shop.r2rml.ttl"
    assert b"rr:TriplesMap" in p.read_bytes()


def test_import_without_generate_r2rml_has_no_row(client: TestClient, shop_db: Path) -> None:
    """Default off: no companion file, no DB row, response r2rml is null."""
    payload = _imported(client, shop_db, generate_r2rml=False)
    assert payload["r2rml"] is None
    assert _r2rml_row(payload["ontologyId"]) is None


def test_import_delete_cascades_r2rml(client: TestClient, shop_db: Path) -> None:
    """Deleting the ontology drops the companion row and its file.

    The row goes in an explicit delete stage (SQLite runs without FK
    enforcement); the file dies with the store directory.
    """
    payload = _imported(client, shop_db, generate_r2rml=True)
    row = _r2rml_row(payload["ontologyId"])
    path = Path(row.storage_path)
    r = client.delete(f"/api/v1/ontologies/{payload['ontologyId']}")
    assert r.status_code == 200
    assert _r2rml_row(payload["ontologyId"]) is None
    assert not path.exists()


def test_import_schema_hash_covers_kept_tables_only(client: TestClient, shop_db: Path) -> None:
    """Unchecked tables must not enter the stored P3 drift baseline.

    The spec pins the hash to the *selected* subset — a user editing a
    table they never checked must not flip it. The wire body carries the
    full reflection, so the endpoint must filter before hashing.
    """
    schema = _reflected(client, shop_db)
    schema["tables"].append(
        TableSpec(
            name="audit_log",
            columns=[
                ColumnSpec(name="id", type="INTEGER", nullable=False, primary_key=True, unique=True)
            ],
        ).model_dump(by_alias=True)
    )
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json={
            "schema": schema,
            "decisions": DECISIONS_OBJ,
            "rejectedClassNames": [],
            "namespace": "https://local/shop#",
            "generateR2rml": True,
        },
    )
    assert r.status_code == 201
    row = _r2rml_row(r.json()["data"]["ontologyId"])
    full = SchemaModel.model_validate(schema)
    kept = full.model_copy(update={"tables": [t for t in full.tables if t.name != "audit_log"]})
    assert row is not None
    assert row.schema_hash == schema_hash(kept)
    assert row.schema_hash != schema_hash(full)


def test_import_rejects_unqualified_decision_refs(client: TestClient, shop_db: Path) -> None:
    """sourceColumn/sourceFk missing the table prefix must 422 at the boundary.

    The R2RML renderer splits on the dot; without this guard an LLM that
    writes "name" instead of "customer.name" 500s after the ontology row
    is already committed (and the retry then hits DUPLICATE_FILENAME).
    """
    body = {
        "schema": _reflected(client, shop_db),
        "rejectedClassNames": [],
        "namespace": "https://local/shop#",
        "generateR2rml": True,
    }
    bare_column = {
        **DECISIONS_OBJ,
        "dataProperties": [
            {**dp, "sourceColumn": "name"} for dp in DECISIONS_OBJ["dataProperties"]
        ],
    }
    bare_fk = {
        **DECISIONS_OBJ,
        "objectProperties": [
            {
                "name": "hasCustomer",
                "domain": "Order",
                "range": "Customer",
                "sourceFk": "customer_id",
            }
        ],
    }
    for decisions in (bare_column, bare_fk):
        r = client.post("/api/v1/ontologies/drafting/import", json={**body, "decisions": decisions})
        assert r.status_code == 422


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


def _import_body(client: TestClient, shop_db: Path, decisions: dict, **over: object) -> dict:
    """Standard import body with per-test overrides."""
    body: dict = {
        "schema": _reflected(client, shop_db),
        "decisions": decisions,
        "rejectedClassNames": [],
        "namespace": "https://local/shop#",
    }
    body.update(over)
    return body


def _export_turtle(client: TestClient, oid: str) -> str:
    return client.get(f"/api/v1/ontologies/{oid}/export/file", params={"format": "turtle"}).json()[
        "data"
    ]["content"]


def test_import_lint_findings_wire_camel(client: TestClient, shop_db: Path) -> None:
    """Guardrail findings ride the camelCase wire like every other lint surface.

    missing-version fires on every draft, so findings are never empty here.
    """
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json=_import_body(client, shop_db, DECISIONS_OBJ),
    )
    assert r.status_code == 201
    findings = r.json()["data"]["lintFindings"]
    assert findings
    for f in findings:
        assert "ruleId" in f and "rule_id" not in f
        assert "durationMs" in f and "duration_ms" not in f
        for hit in f["findings"]:
            assert "subjectCurie" in hit and "subject_curie" not in hit


def test_import_honors_label_language(client: TestClient, shop_db: Path) -> None:
    """labelLanguage=en tags rendered labels @en instead of the zh default."""
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json=_import_body(client, shop_db, DECISIONS_OBJ, labelLanguage="en"),
    )
    assert r.status_code == 201
    src = _export_turtle(client, r.json()["data"]["ontologyId"])
    assert '"客户"@en' in src
    assert "@zh" not in src


def test_import_escapes_multiline_label(client: TestClient, shop_db: Path) -> None:
    """A newline inside an LLM label must not kill the whole run at parse."""
    decisions = {
        "classes": [
            {
                "name": "Customer",
                "label": "客户\n备注行",
                "comment": None,
                "sourceTable": "customer",
                "parentName": None,
            },
            {
                "name": "Order",
                "label": "订单",
                "comment": None,
                "sourceTable": "orders",
                "parentName": None,
            },
        ],
        "objectProperties": [],
        "dataProperties": [],
    }
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json=_import_body(client, shop_db, decisions),
    )
    assert r.status_code == 201
    src = _export_turtle(client, r.json()["data"]["ontologyId"])
    assert "备注行" in src  # the label survived, escaped or long-form quoted


def test_import_rejects_ttl_breaking_names(client: TestClient, shop_db: Path) -> None:
    """A whitespace-bearing name 422s naming the field, not an opaque parse death."""
    decisions = {
        "classes": [
            {
                "name": "Bad Name",
                "label": "坏名字",
                "comment": None,
                "sourceTable": "customer",
                "parentName": None,
            }
        ],
        "objectProperties": [],
        "dataProperties": [],
    }
    r = client.post(
        "/api/v1/ontologies/drafting/import",
        json=_import_body(client, shop_db, decisions),
    )
    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_cancel_endpoint_404_on_unknown_job(client: TestClient) -> None:
    """Cancelling a job id that never existed reads as plain 404."""
    r = client.post("/api/v1/ontologies/drafting/jobs/zzz/cancel")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"


def test_cancel_endpoint_stops_a_running_job(
    client: TestClient, shop_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wizard's 放弃 button hits this endpoint.

    A running generate settles as cancelled (never done/failed) and the
    poll payload says so.
    """

    async def slow_draft(
        provider, schema, *, namespace, label_language, progress=None, should_cancel=None
    ):
        while not (should_cancel and should_cancel()):
            await asyncio.sleep(0.01)
        raise CoreError("DRAFT_CANCELLED", "draft cancelled by user")

    monkeypatch.setattr(drafting_router, "generate_draft", slow_draft)
    client.app.dependency_overrides[get_ai_provider] = lambda: FakeProvider([])
    try:
        r = client.post(
            "/api/v1/ontologies/drafting/generate", json={"schema": _reflected(client, shop_db)}
        )
        assert r.status_code == 202
        job_id = r.json()["data"]["jobId"]
        r2 = client.post(f"/api/v1/ontologies/drafting/jobs/{job_id}/cancel")
        assert r2.status_code == 200
        assert r2.json()["data"]["status"] == "cancelled"
    finally:
        client.app.dependency_overrides.clear()
    d = None
    for _ in range(200):
        d = client.get(f"/api/v1/ontologies/drafting/jobs/{job_id}").json()["data"]
        if d["status"] != "running":
            break
        time.sleep(0.05)
    assert d is not None and d["status"] == "cancelled"
