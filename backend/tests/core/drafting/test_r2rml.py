"""R2RML serializer: narrow-subset render, parse-back, schema hash."""

import pyoxigraph as ox

from ontoworkbench.core.drafting.merge import merge_decisions
from ontoworkbench.core.drafting.models import (
    ColumnSpec,
    DecisionSet,
    ForeignKeySpec,
    SchemaModel,
    TableSpec,
)
from ontoworkbench.core.drafting.r2rml import (
    parse_r2rml,
    render_r2rml,
    schema_hash,
)

NS = "https://local/shop#"


def _col(name, **kw):
    return ColumnSpec(
        name=name,
        type=kw.pop("type", "INTEGER"),
        nullable=True,
        primary_key=kw.pop("primary_key", False),
        unique=kw.pop("unique", False),
        comment=None,
    )


def _decisions():
    return DecisionSet(
        classes=[
            {"name": "Customer", "label": "客户", "sourceTable": "customer"},
            {"name": "Order", "label": "订单", "sourceTable": "orders"},
        ],
        objectProperties=[
            {
                "name": "hasCustomer",
                "domain": "Order",
                "range": "Customer",
                "sourceFk": "orders.customer_id",
            },
        ],
        dataProperties=[
            {
                "name": "name",
                "domain": "Customer",
                "datatype": "xsd:string",
                "sourceColumn": "customer.name",
            },
        ],
    )


def _schema(*tables):
    return SchemaModel(database_name="shop", tables=list(tables))


SHOP_DB = _schema(
    TableSpec(name="customer", columns=[_col("id", primary_key=True), _col("name")]),
    TableSpec(
        name="orders",
        columns=[_col("id", primary_key=True), _col("customer_id")],
        foreign_keys=[ForeignKeySpec(column="customer_id", ref_table="customer", ref_column="id")],
    ),
)


def _render(schema=SHOP_DB):
    draft = merge_decisions([_decisions()], schema)
    return render_r2rml(draft, schema, NS)


def test_render_golden_two_tables():
    """Golden: two tables with a FK render to the exact narrow-subset Turtle."""
    r = _render()
    assert r.skipped_tables == []
    assert r.ttl.decode() == (
        "@prefix rr: <http://www.w3.org/ns/r2rml#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        "@prefix shop: <https://local/shop#> .\n"
        "\n"
        "<https://local/shop/r2rml/Customer> a rr:TriplesMap ;\n"
        '    rr:logicalTable [ rr:tableName "customer" ] ;\n'
        "    rr:subjectMap [\n"
        '        rr:template "https://local/shop/customer/{id}" ;\n'
        "        rr:class shop:Customer ;\n"
        "    ] ;\n"
        "    rr:predicateObjectMap [\n"
        "        rr:predicate shop:name ;\n"
        '        rr:objectMap [ rr:column "name" ; rr:datatype xsd:string ] ;\n'
        "    ] .\n"
        "\n"
        "<https://local/shop/r2rml/Order> a rr:TriplesMap ;\n"
        '    rr:logicalTable [ rr:tableName "orders" ] ;\n'
        "    rr:subjectMap [\n"
        '        rr:template "https://local/shop/orders/{id}" ;\n'
        "        rr:class shop:Order ;\n"
        "    ] ;\n"
        "    rr:predicateObjectMap [\n"
        "        rr:predicate shop:hasCustomer ;\n"
        "        rr:objectMap [\n"
        "            rr:parentTriplesMap <https://local/shop/r2rml/Customer> ;\n"
        '            rr:joinCondition [ rr:child "customer_id" ; rr:parent "id" ] ;\n'
        "        ] ;\n"
        "    ] .\n"
    )


def test_rendered_ttl_parses_as_turtle():
    """The rendered bytes must be valid Turtle (all maps land in the graph)."""
    store = ox.Store()
    store.load(input=_render().ttl, format=ox.RdfFormat.TURTLE, to_graph=ox.DefaultGraph())
    assert len(list(store)) >= 10  # 两图 POM 全部落图


def test_render_skips_pkless_table_and_its_fks():
    """No PK and no single UNIQUE: table is skipped and FK props referencing it drop too."""
    schema = _schema(
        TableSpec(name="customer", columns=[_col("id", primary_key=True)]),
        TableSpec(name="audit", columns=[_col("event"), _col("at")]),
    )
    decisions = DecisionSet(
        classes=[
            {"name": "Customer", "label": "c", "sourceTable": "customer"},
            {"name": "Audit", "label": "a", "sourceTable": "audit"},
        ],
        objectProperties=[
            {
                "name": "hasAudit",
                "domain": "Customer",
                "range": "Audit",
                "sourceFk": "customer.audit_id",
            },
        ],
        dataProperties=[],
    )
    r = render_r2rml(merge_decisions([decisions], schema), schema, NS)
    assert r.skipped_tables == ["audit"]
    out = r.ttl.decode()
    assert "Audit" not in out and "hasAudit" not in out
    assert "customer" in out  # 正常表不受影响


def test_render_unique_fallback_and_multi_column_pk():
    """Single UNIQUE falls back for identity; multi-column PK concatenates the template."""
    schema = _schema(
        TableSpec(name="users", columns=[_col("email", unique=True)]),
        TableSpec(
            name="order_items",
            columns=[_col("order_id", primary_key=True), _col("product_id", primary_key=True)],
        ),
    )
    decisions = DecisionSet(
        classes=[
            {"name": "User", "label": "u", "sourceTable": "users"},
            {"name": "OrderItem", "label": "oi", "sourceTable": "order_items"},
        ],
        objectProperties=[],
        dataProperties=[],
    )
    r = render_r2rml(merge_decisions([decisions], schema), schema, NS)
    assert r.skipped_tables == []
    out = r.ttl.decode()
    assert 'rr:template "https://local/shop/users/{email}"' in out
    assert 'rr:template "https://local/shop/order_items/{order_id}/{product_id}"' in out


def test_render_escapes_hostile_names():
    """A quote inside a table name must survive as escaped Turtle, not break the parse."""
    schema = _schema(
        TableSpec(name='we"ird', columns=[_col("id", primary_key=True)]),
    )
    decisions = DecisionSet(
        classes=[{"name": "Weird", "label": "w", "sourceTable": 'we"ird'}],
        objectProperties=[],
        dataProperties=[],
    )
    store = ox.Store()
    store.load(
        input=render_r2rml(merge_decisions([decisions], schema), schema, NS).ttl,
        format=ox.RdfFormat.TURTLE,
        to_graph=ox.DefaultGraph(),
    )  # 不抛即合法


def test_parse_round_trip():
    """parse_r2rml recovers the rendered structure: tables, classes, column and FK props."""
    maps = parse_r2rml(_render().ttl, NS)
    assert [m.class_name for m in maps] == ["Customer", "Order"]
    cust = maps[0]
    assert cust.table == "customer"
    assert cust.subject_template == "https://local/shop/customer/{id}"
    assert [(p.predicate, p.column, p.datatype) for p in cust.column_props] == [
        ("name", "name", "xsd:string")
    ]
    order = maps[1]
    fk = order.fk_props[0]
    assert (fk.predicate, fk.child_column, fk.parent_table, fk.parent_column) == (
        "hasCustomer",
        "customer_id",
        "customer",
        "id",
    )


def test_schema_hash_order_independent_and_subset_scoped():
    """Hash ignores reflection order but tracks the selected subset."""
    a = _schema(SHOP_DB.tables[0], SHOP_DB.tables[1])
    b = _schema(*reversed(SHOP_DB.tables))  # 反射顺序不同
    assert schema_hash(a) == schema_hash(b)
    only_customer = _schema(SHOP_DB.tables[0])  # 子集不同 → 哈希不同
    assert schema_hash(a) != schema_hash(only_customer)
