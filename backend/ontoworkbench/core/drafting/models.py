"""Drafting data models (spec §5): reflected schema + LLM decisions.

All models serialize camelCase on the wire (to_camel aliases) — the wizard
sends SchemaModel subsets back verbatim and posts DecisionSet subsets.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Names interpolate into "prefix:Name" Turtle positions unquoted: no
# whitespace, quotes, angle brackets or backslashes may ride along.
NAME_SAFE = r"^[^\s\"'<>\\]+$"

# Source refs are "table.column" — the R2RML renderer splits on the dot,
# and an LLM dropping the table prefix would 500 after the ontology row
# is already committed (generate retries, import 422s).
QUALIFIED_REF = r"^[^\s.]+\.[^\s.]+$"


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

    # Names land raw in "prefix:Name" positions of the Turtle render, so a
    # name carrying whitespace/quotes would kill the parse — reject here with
    # a named field instead (generate retries, import 422s).
    name: str = Field(pattern=NAME_SAFE)
    label: str
    comment: str | None = None
    source_table: str
    parent_name: str | None = Field(default=None, pattern=NAME_SAFE)


class ObjectPropertyDecision(CamelModel):
    """The LLM's verdict (or the merger's fallback) on one FK → property."""

    name: str = Field(pattern=NAME_SAFE)
    label: str | None = None
    domain: str = Field(pattern=NAME_SAFE)
    range: str = Field(pattern=NAME_SAFE)
    source_fk: str = Field(pattern=QUALIFIED_REF)  # "table.column" of the FK edge


class DataPropertyDecision(CamelModel):
    """The LLM's verdict on one column → data property."""

    name: str = Field(pattern=NAME_SAFE)
    label: str | None = None
    domain: str = Field(pattern=NAME_SAFE)
    datatype: str
    source_column: str = Field(pattern=QUALIFIED_REF)  # "table.column"


class DecisionSet(CamelModel):
    """One batch's structured output (or the wizard's checked subset)."""

    classes: list[ClassDecision] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDecision] = Field(default_factory=list)
    data_properties: list[DataPropertyDecision] = Field(default_factory=list)
