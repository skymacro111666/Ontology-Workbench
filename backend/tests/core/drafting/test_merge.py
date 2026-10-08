"""Merger: cross-batch FK completion, cascade rejections, TTL rendering."""

from ontoworkbench.core.drafting.merge import (
    apply_rejections,
    merge_decisions,
    render_ttl,
)
from ontoworkbench.core.drafting.models import (
    ClassDecision,
    ColumnSpec,
    DataPropertyDecision,
    DecisionSet,
    ForeignKeySpec,
    ObjectPropertyDecision,
    SchemaModel,
    TableSpec,
)


def _schema() -> SchemaModel:
    """customer/orders with one FK edge; batches split across it."""
    return SchemaModel(
        database_name="shop",
        tables=[
            TableSpec(
                name="customer",
                comment=None,
                columns=[
                    ColumnSpec(
                        name="id", type="INTEGER", nullable=False, primary_key=True, unique=True
                    )
                ],
                foreign_keys=[],
            ),
            TableSpec(
                name="orders",
                comment=None,
                columns=[
                    ColumnSpec(
                        name="customer_id",
                        type="INTEGER",
                        nullable=False,
                        primary_key=False,
                        unique=False,
                    )
                ],
                foreign_keys=[
                    ForeignKeySpec(column="customer_id", ref_table="customer", ref_column="id")
                ],
            ),
        ],
    )


def _batches() -> list[DecisionSet]:
    """Batch 1 drafts customer; batch 2 drafts orders with Order ⊑ Customer."""
    return [
        DecisionSet(
            classes=[
                ClassDecision(
                    name="Customer",
                    label="客户",
                    comment=None,
                    source_table="customer",
                    parent_name=None,
                )
            ],
            data_properties=[
                DataPropertyDecision(
                    name="id",
                    label=None,
                    domain="Customer",
                    datatype="xsd:integer",
                    source_column="customer.id",
                )
            ],
        ),
        DecisionSet(
            classes=[
                ClassDecision(
                    name="Order",
                    label="订单",
                    comment=None,
                    source_table="orders",
                    parent_name="Customer",
                )
            ],
            object_properties=[],
        ),
    ]


def test_cross_batch_fk_prop_generated_with_default_name() -> None:
    """A FK edge nobody covered gets a deterministic hasX property."""
    draft = merge_decisions(_batches(), _schema())
    fk_props = [p for p in draft.object_properties if p.source_fk == "orders.customer_id"]
    assert len(fk_props) == 1
    assert (fk_props[0].domain, fk_props[0].range, fk_props[0].name) == (
        "Order",
        "Customer",
        "hasCustomer",
    )


def test_llm_covered_fk_not_duplicated() -> None:
    """An LLM decision on the same source_fk wins; no duplicate default."""
    batches = _batches()
    batches[1] = batches[1].model_copy(
        update={
            "object_properties": [
                ObjectPropertyDecision(
                    name="placedBy",
                    label="下单方",
                    domain="Order",
                    range="Customer",
                    source_fk="orders.customer_id",
                )
            ]
        }
    )
    draft = merge_decisions(batches, _schema())
    fk_props = [p for p in draft.object_properties if p.source_fk == "orders.customer_id"]
    assert len(fk_props) == 1 and fk_props[0].name == "placedBy"


def test_class_dedup_across_batches() -> None:
    """The same class from two batches merges (first label wins, no dupes)."""
    b = _batches()
    b[1].classes.append(
        ClassDecision(
            name="Customer",
            label="客户 dup",
            comment=None,
            source_table="customer",
            parent_name=None,
        )
    )
    draft = merge_decisions(b, _schema())
    assert [c.name for c in draft.classes].count("Customer") == 1


def test_apply_rejections_cascades() -> None:
    """Rejecting a class drops its properties and re-roots children.

    Data properties of the rejected class and FK properties touching it go;
    Order's parent_name re-roots to None (no surviving ancestor).
    """
    draft = merge_decisions(_batches(), _schema())
    apply_rejections(draft, {"Customer"})
    names = [c.name for c in draft.classes]
    assert "Customer" not in names and "Order" in names
    assert all(p.domain != "Customer" and p.range != "Customer" for p in draft.object_properties)
    assert all(p.domain != "Customer" for p in draft.data_properties)
    order = next(c for c in draft.classes if c.name == "Order")
    assert order.parent_name is None  # re-rooted: no surviving ancestor


def test_render_ttl_parses_and_carries_labels() -> None:
    """The TTL renders with prefix header, labels, and FK property."""
    draft = merge_decisions(_batches(), _schema())
    ttl = render_ttl(
        draft, namespace="https://local/shop#", prefix="shop", title="shop", label_language="zh"
    )
    text = ttl.decode("utf-8")
    assert "@prefix shop: <https://local/shop#> ." in text
    assert "shop:Customer a owl:Class" in text
    assert "shop:hasCustomer a owl:ObjectProperty" in text
    assert '"客户"@zh' in text
