"""prompt builder: schema payload, design guidance, output template."""

from ontoworkbench.core.drafting.models import (
    ColumnSpec,
    ForeignKeySpec,
    SchemaModel,
    TableSpec,
)
from ontoworkbench.core.drafting.prompt import build_prompt

SCHEMA = SchemaModel(
    database_name="shop",
    tables=[
        TableSpec(
            name="customer",
            comment="买方",
            columns=[
                ColumnSpec(
                    name="id", type="INTEGER", nullable=False, primary_key=True, unique=True
                ),
                ColumnSpec(
                    name="name",
                    type="VARCHAR(80)",
                    nullable=False,
                    primary_key=False,
                    unique=False,
                ),
            ],
            foreign_keys=[],
        ),
        TableSpec(
            name="orders",
            comment=None,
            columns=[
                ColumnSpec(
                    name="id", type="INTEGER", nullable=False, primary_key=True, unique=False
                ),
                ColumnSpec(
                    name="customer_id",
                    type="INTEGER",
                    nullable=False,
                    primary_key=False,
                    unique=False,
                ),
                ColumnSpec(
                    name="status",
                    type="VARCHAR(20)",
                    nullable=True,
                    primary_key=False,
                    unique=False,
                ),
            ],
            foreign_keys=[
                ForeignKeySpec(column="customer_id", ref_table="customer", ref_column="id")
            ],
        ),
    ],
)


def test_prompt_contains_schema_rules_and_template() -> None:
    """Schema JSON, naming rules, restraint clause and template all present."""
    p = build_prompt(SCHEMA, ["customer", "orders", "product"], "https://local/shop#", "zh")
    for needle in [
        "customer",
        "orders",
        "product",
        "PascalCase",
        "camelCase",
        "objectProperties",
        "dataProperties",
        "sourceTable",
        "sourceFk",
        "Direct Mapping",
        "https://local/shop#",
        '"zh"',
        "买方",
        "cardinality",
    ]:
        assert needle in p, needle


def test_prompt_json_block_is_parseable() -> None:
    """The embedded schema JSON is extractable and complete."""
    import json

    p = build_prompt(SCHEMA, ["customer", "orders"], "https://local/shop#", "zh")
    start, end = p.find("```json"), p.rfind("```")
    block = p[start + len("```json") : end].strip()
    parsed = json.loads(block)
    assert parsed["databaseName"] == "shop"
    assert {t["name"] for t in parsed["tables"]} == {"customer", "orders"}
