"""Drafting data models (spec §5): reflected schema + LLM decisions.

All models serialize camelCase on the wire (to_camel aliases) — the wizard
sends SchemaModel subsets back verbatim and posts DecisionSet subsets.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Wire style: camelCase aliases, snake_case accepted."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ColumnSpec(CamelModel):
    """One reflected column."""

    name: str
    type: str
    nullable: bool
    primary_key: bool
    unique: bool
    comment: str | None = None


class ForeignKeySpec(CamelModel):
    """One FK edge: this column → that table.column."""

    column: str
    ref_table: str
    ref_column: str


class TableSpec(CamelModel):
    """One reflected table."""

    name: str
    comment: str | None = None
    columns: list[ColumnSpec] = Field(default_factory=list)
    foreign_keys: list[ForeignKeySpec] = Field(default_factory=list)


class SchemaModel(CamelModel):
    """A reflected database (possibly the user-selected subset)."""

    database_name: str
    tables: list[TableSpec] = Field(default_factory=list)


class ClassDecision(CamelModel):
    """The LLM's verdict on one table → class."""

    name: str
    label: str
    comment: str | None = None
    source_table: str
    parent_name: str | None = None


class ObjectPropertyDecision(CamelModel):
    """The LLM's verdict (or the merger's fallback) on one FK → property."""

    name: str
    label: str | None = None
    domain: str
    range: str
    source_fk: str  # "table.column" of the FK edge


class DataPropertyDecision(CamelModel):
    """The LLM's verdict on one column → data property."""

    name: str
    label: str | None = None
    domain: str
    datatype: str
    source_column: str  # "table.column"


class DecisionSet(CamelModel):
    """One batch's structured output (or the wizard's checked subset)."""

    classes: list[ClassDecision] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDecision] = Field(default_factory=list)
    data_properties: list[DataPropertyDecision] = Field(default_factory=list)
