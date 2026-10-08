"""generate_draft pipeline: batch loop, progress, stats, table cap."""

import asyncio

import pytest

from ontoworkbench.core.ai.fake import FakeProvider
from ontoworkbench.core.ai.types import ModelResponse
from ontoworkbench.core.drafting.models import (
    ColumnSpec,
    ForeignKeySpec,
    SchemaModel,
    TableSpec,
)
from ontoworkbench.core.drafting.pipeline import DraftResult, generate_draft
from ontoworkbench.core.errors import CoreError

DECISIONS_CUSTOMER = (
    '```json\n{"classes": [{"name": "Customer", "label": "客户", "comment": null, '
    '"sourceTable": "customer", "parentName": null}], '
    '"objectProperties": [], '
    '"dataProperties": [{"name": "name", "label": null, "domain": "Customer", '
    '"datatype": "xsd:string", "sourceColumn": "customer.name"}]}\n```'
)
DECISIONS_ORDERS = (
    '```json\n{"classes": [{"name": "Order", "label": "订单", "comment": null, '
    '"sourceTable": "orders", "parentName": "Customer"}], '
    '"objectProperties": [], "dataProperties": []}\n```'
)


DECISIONS_BOTH = (
    '```json\n{"classes": [{"name": "Customer", "label": "客户", "comment": null, '
    '"sourceTable": "customer", "parentName": null}, '
    '{"name": "Order", "label": "订单", "comment": null, '
    '"sourceTable": "orders", "parentName": "Customer"}], '
    '"objectProperties": [], '
    '"dataProperties": [{"name": "name", "label": null, "domain": "Customer", '
    '"datatype": "xsd:string", "sourceColumn": "customer.name"}]}\n```'
)


def _table(name: str, ref: str | None = None) -> TableSpec:
    """One table with an optional FK edge."""
    return TableSpec(
        name=name,
        comment=None,
        columns=[
            ColumnSpec(name="id", type="INTEGER", nullable=False, primary_key=True, unique=False),
            ColumnSpec(
                name="name", type="VARCHAR(80)", nullable=True, primary_key=False, unique=False
            ),
        ],
        foreign_keys=(
            [ForeignKeySpec(column=f"{ref}_id", ref_table=ref, ref_column="id")] if ref else []
        ),
    )


def _schema(n_tables: int = 2) -> SchemaModel:
    """FK-linked pair by default; plus (n-2) independent tables when asked."""
    tables = [_table("customer"), _table("orders", "customer")]
    for i in range(n_tables - 2):
        tables.append(_table(f"t{i:02d}"))
    return SchemaModel(database_name="shop", tables=tables)


def test_single_batch_flow() -> None:
    """One batch: decisions merged, TTL rendered, guardrails run, stats filled."""
    p = FakeProvider([ModelResponse(text=DECISIONS_BOTH, in_tokens=10, out_tokens=5)])
    result = asyncio.run(
        generate_draft(p, _schema(2), namespace="https://local/shop#", label_language="zh")
    )
    assert isinstance(result, DraftResult)
    assert [c.name for c in result.decisions.classes] == ["Customer", "Order"]
    # FK completion ran (orders.customer_id uncovered by the LLM)
    assert any(op.name == "hasCustomer" for op in result.decisions.object_properties)
    assert b"shop:Customer a owl:Class" in result.ttl
    assert isinstance(result.lint_findings, list)
    assert result.stats["classCount"] == 2
    assert result.stats["batchCount"] == 1
    assert result.stats["inTokens"] == 10 and result.stats["outTokens"] == 5
    assert result.stats["elapsedMs"] >= 0


def test_two_batches_with_progress() -> None:
    """batch_tables=1 forces one table per batch; progress fires per batch."""
    p = FakeProvider(
        [
            ModelResponse(text=DECISIONS_CUSTOMER, in_tokens=10, out_tokens=5),
            ModelResponse(text=DECISIONS_ORDERS, in_tokens=8, out_tokens=4),
            # FK pair customer+orders stays as one component of 2 → split into 2
            # batches of 1; then each independent table needs one more response...
        ]
    )
    # keep it to the FK pair so the scripted count is exact
    schema = _schema(2)
    calls: list[tuple[int, int]] = []
    result = asyncio.run(
        generate_draft(
            p,
            schema,
            namespace="https://local/shop#",
            label_language="zh",
            batch_tables=1,
            progress=lambda k, n: calls.append((k, n)),
        )
    )
    assert calls == [(1, 2), (2, 2)]
    assert result.stats["batchCount"] == 2
    assert result.stats["inTokens"] == 18 and result.stats["outTokens"] == 9


def test_retry_on_bad_json_then_success() -> None:
    """A garbage first output retries once and succeeds (spec §1.4)."""
    p = FakeProvider(
        [
            ModelResponse(text="oops not json"),
            ModelResponse(text=DECISIONS_CUSTOMER, in_tokens=1, out_tokens=1),
            ModelResponse(text=DECISIONS_ORDERS, in_tokens=1, out_tokens=1),
        ]
    )
    result = asyncio.run(
        generate_draft(
            p, _schema(2), namespace="https://local/shop#", label_language="zh", batch_tables=1
        )
    )
    assert result.stats["batchCount"] == 2


def test_table_cap_guard() -> None:
    """> max_tables rejects before any provider call."""
    p = FakeProvider([])
    with pytest.raises(CoreError) as ei:
        asyncio.run(
            generate_draft(
                p, _schema(3), namespace="https://local/shop#", label_language="zh", max_tables=2
            )
        )
    assert ei.value.code == "VALIDATION_ERROR"


def test_knob_env_batch_size(monkeypatch: pytest.MonkeyPatch) -> None:
    """AI_DRAFT_BATCH_TABLES feeds the default batch size."""
    monkeypatch.setenv("AI_DRAFT_BATCH_TABLES", "1")
    p = FakeProvider(
        [
            ModelResponse(text=DECISIONS_CUSTOMER, in_tokens=1, out_tokens=1),
            ModelResponse(text=DECISIONS_ORDERS, in_tokens=1, out_tokens=1),
        ]
    )
    result = asyncio.run(
        generate_draft(p, _schema(2), namespace="https://local/shop#", label_language="zh")
    )
    assert result.stats["batchCount"] == 2
