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
    validate_r2rml,
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


# --- R2RML P2: three-layer save gate -------------------------------------


GATE_NS = "https://local/shop#"

GATE_SCHEMA = SchemaModel(
    database_name="shop",
    tables=[
        TableSpec(
            name="customer",
            columns=[
                _col("id", primary_key=True, unique=True),
                _col("name", type="VARCHAR"),
            ],
        )
    ],
)

VALID_TTL = (
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
)


def test_gate_accepts_valid_subset():
    """窄子集自产文档过三层门(空 findings)."""
    assert validate_r2rml(VALID_TTL.encode(), GATE_NS, GATE_SCHEMA) == []


def test_gate_l1_rejects_bad_syntax():
    """坏 Turtle 在 L1 被拒,信息含解析错误."""
    findings = validate_r2rml(b"@prefix broken <<", GATE_NS, GATE_SCHEMA)
    assert len(findings) == 1
    assert findings[0].layer == 1


def test_gate_l2_rejects_superset_triples():
    """rr:join(合法 Turtle、R2RML 超集)在 L2 被逐三元组拒绝."""
    superset = VALID_TTL.replace(
        '        rr:objectMap [ rr:column "name" ; rr:datatype xsd:string ] ;\n',
        '        rr:objectMap [ rr:column "name" ; rr:datatype xsd:string ;\n'
        '            rr:join ( [ rr:child "a" ] [ rr:parent "b" ] ) ] ;\n',
    )
    findings = validate_r2rml(superset.encode(), GATE_NS, GATE_SCHEMA)
    assert findings and all(f.layer == 2 for f in findings)
    assert any(f.location for f in findings)


def test_gate_l2_rejects_sql_query_superset():
    """rr:sqlQuery 逻辑表(超集核心风险)被拒."""
    sql = VALID_TTL.replace(
        '    rr:logicalTable [ rr:tableName "customer" ] ;\n',
        '    rr:logicalTable [ rr:sqlQuery "SELECT id FROM customer" ] ;\n',
    )
    findings = validate_r2rml(sql.encode(), GATE_NS, GATE_SCHEMA)
    assert any(f.layer == 2 for f in findings)


def test_gate_l2_rejects_annotation_triple():
    """夹带 rdfs:label 注解三元组(子集外谓词)被拒."""
    annotated = (
        VALID_TTL
        + "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        + '\n<https://local/shop/r2rml/Customer> rdfs:label "map" .\n'
    )
    findings = validate_r2rml(annotated.encode(), GATE_NS, GATE_SCHEMA)
    # Quads carry full IRIs — match the label predicate, not the prefix form.
    assert any(f.layer == 2 and "rdf-schema#label" in (f.location or "") for f in findings)


def test_gate_l2_rejects_dangling_parent():
    """ParentTriplesMap 指向非 TriplesMap 的 IRI 被拒."""
    dangling = VALID_TTL + (
        "\n<https://local/shop/r2rml/Customer> rr:predicateObjectMap [\n"
        "    rr:predicate shop:rel ;\n"
        "    rr:objectMap [ rr:parentTriplesMap <https://nope/m> ]\n"
        "] .\n"
    )
    findings = validate_r2rml(dangling.encode(), GATE_NS, GATE_SCHEMA)
    assert any(f.layer == 2 for f in findings)


def test_gate_l3_unknown_column_lists_available():
    """拼错列名在 L3 被拒,且信息列出该表可用列."""
    typo = VALID_TTL.replace('rr:column "name"', 'rr:column "nme"')
    findings = validate_r2rml(typo.encode(), GATE_NS, GATE_SCHEMA)
    assert findings and all(f.layer == 3 for f in findings)
    assert "id、name" in findings[0].message  # 可用列清单(排序拼接)


def test_gate_l3_template_placeholder_unknown():
    """Template 占位符引用不存在的列被拒."""
    typo = VALID_TTL.replace("customer/{id}", "customer/{idd}")
    findings = validate_r2rml(typo.encode(), GATE_NS, GATE_SCHEMA)
    assert any(f.layer == 3 and "{idd}" in f.message for f in findings)


def test_gate_l3_fk_columns_checked():
    """FK join 的 child/parent 列都要在快照中(此处 child 拼错)."""
    fk = VALID_TTL + (
        "\n<https://local/shop/r2rml/Customer> rr:predicateObjectMap [\n"
        "    rr:predicate shop:rel ;\n"
        "    rr:objectMap [ rr:parentTriplesMap <https://local/shop/r2rml/Customer> ;\n"
        '        rr:joinCondition [ rr:child "nm" ; rr:parent "id" ] ]\n'
        "] .\n"
    )
    findings = validate_r2rml(fk.encode(), GATE_NS, GATE_SCHEMA)
    assert any(f.layer == 3 and "nm" in f.message for f in findings)


def test_gate_l3_datatype_must_be_iri():
    """Datatype 给成字面量在 L3 被拒(spec §4.1 L3 行)."""
    bad_dt = VALID_TTL.replace("rr:datatype xsd:string", 'rr:datatype "string"')
    findings = validate_r2rml(bad_dt.encode(), GATE_NS, GATE_SCHEMA)
    assert any(f.layer == 3 and "datatype" in f.message for f in findings)


def test_gate_l3_skipped_without_snapshot():
    """无快照(P1 存量行):L3 整体跳过,坏列名也能过(降级=仅 L1+L2)."""
    typo = VALID_TTL.replace('rr:column "name"', 'rr:column "nme"')
    assert validate_r2rml(typo.encode(), GATE_NS, None) == []


# --- final-review fixes: completeness + foreign-IRI maps --------------------


def test_gate_l2_rejects_incomplete_shapes():
    """删块的残缺编辑(逐三元组仍合法)在 L2 报带定位 finding,而非 parse KeyError→500."""
    cases = {
        "缺 subjectMap": VALID_TTL.replace(
            "    rr:subjectMap [\n"
            '        rr:template "https://local/shop/customer/{id}" ;\n'
            "        rr:class shop:Customer ;\n"
            "    ] ;\n",
            "",
        ),
        "缺 template": VALID_TTL.replace(
            '        rr:template "https://local/shop/customer/{id}" ;\n', ""
        ),
        "POM 缺 predicate": VALID_TTL.replace("        rr:predicate shop:name ;\n", ""),
        "refObjectMap 缺 joinCondition": VALID_TTL.replace(
            '        rr:objectMap [ rr:column "name" ; rr:datatype xsd:string ] ;\n',
            "        rr:objectMap [ rr:parentTriplesMap <https://local/shop/r2rml/Customer> ] ;\n",
        ),
    }
    for label, ttl in cases.items():
        findings = validate_r2rml(ttl.encode(), GATE_NS, GATE_SCHEMA)
        assert findings and all(f.layer == 2 for f in findings), label
        assert any(f.location for f in findings), label


FOREIGN_TTL = VALID_TTL + (
    "<https://elsewhere.example/m/Order> a rr:TriplesMap ;\n"
    '    rr:logicalTable [ rr:tableName "customer" ] ;\n'
    "    rr:subjectMap [\n"
    '        rr:template "https://local/shop/order/{idd}" ;\n'
    "        rr:class shop:Order ;\n"
    "    ] .\n"
)


def test_gate_l3_checks_foreign_iri_maps():
    """外来 IRI 下的手打 TriplesMap(spec 决策 1 合法)同样过 L3 列校验."""
    findings = validate_r2rml(FOREIGN_TTL.encode(), GATE_NS, GATE_SCHEMA)
    assert any(f.layer == 3 and "{idd}" in f.message for f in findings)


def test_parse_includes_foreign_iri_maps():
    """parse-back 收外来 IRI map → 结构视图可见、可导出校验."""
    maps = parse_r2rml(FOREIGN_TTL.encode(), GATE_NS)
    # 按全 IRI 排序(elsewhere < local),跨前缀时的确定性同样成立
    assert [m.class_name for m in maps] == ["Order", "Customer"]


def test_render_skipped_tables_deduped():
    """两个类共用同一张无主键表(P1 终审 minor):skipped 列表只列一次."""
    schema = _schema(TableSpec(name="notes", columns=[_col("body", type="TEXT")]))
    draft = merge_decisions(
        [
            DecisionSet(
                classes=[
                    {"name": "NoteA", "label": "备注A", "sourceTable": "notes"},
                    {"name": "NoteB", "label": "备注B", "sourceTable": "notes"},
                ],
                objectProperties=[],
                dataProperties=[],
            )
        ],
        schema,
    )
    r = render_r2rml(draft, schema, NS)
    assert r.skipped_tables == ["notes"]
