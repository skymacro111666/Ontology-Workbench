"""Prompt construction for drafting (spec §5.3 step 1, pure function).

One fenced ```json block carries the schema payload; the output contract is
described inline (field lists, not a second fence) so the payload stays the
only machine-extractable block.
"""

from __future__ import annotations

import json

from ontoworkbench.core.drafting.models import SchemaModel

_GUIDANCE = """You are an ontology engineer drafting an OWL 2 ontology from a relational schema.

Design rules:
- Each table maps to one owl:Class, named in PascalCase singular (customers -> Customer).
- Each non-key column maps to one owl:DatatypeProperty in camelCase
  (order_date -> orderDate).
- Each foreign key maps to one owl:ObjectProperty from the FK table's class
  to the referenced table's class.
- Table/column comments become rdfs:label / rdfs:comment material; labels use
  the requested label language.
- Labels must be unique per language across the whole draft — the lint
  duplicate-label rule flags any (lang, value) shared by two entities.
  An FK property labels its relation, not the bare target name
  (所属订单, not 订单); when several FKs target the same class, or the
  same column name recurs across tables, qualify the label with the
  owning side (订单项所属订单) so no two labels collide.
- Columns ending in _type or _status look like enumerations: do NOT mint
  extra classes; mention the suspected enumeration in the class comment.
- The W3C RDB Direct Mapping is your semantic anchor for names and structure.
- Restraint: do NOT generate cardinality restrictions, disjointness axioms,
  or property characteristics — human refinement adds those later.
- Skip technical columns (surrogate ids only as data properties when they
  carry business meaning; rowid-style columns are better omitted).

Output contract — return ONLY one JSON object of exactly this shape (no prose):
{
  "classes": [
    {"name": str PascalCase, "label": str, "comment": str|null,
     "sourceTable": str, "parentName": str|null}
  ],
  "objectProperties": [
    {"name": str camelCase, "label": str|null, "domain": str, "range": str,
     "sourceFk": "table.column"}
  ],
  "dataProperties": [
    {"name": str camelCase, "label": str|null, "domain": str,
     "datatype": "xsd:...", "sourceColumn": "table.column"}
  ]
}
- parentName: a superclass ONLY when the generalization is certain from
  names/comments (e.g. professor -> staff); otherwise null.
- domain/range reference class names you emitted above.
- datatype: xsd:string/integer/decimal/boolean/date/dateTime/double as fits."""


def build_prompt(
    schema: SchemaModel,
    all_table_names: list[str],
    namespace: str,
    label_language: str,
) -> str:
    """Assemble the batch prompt: guidance + schema JSON + global names + wire config."""
    payload = schema.model_dump(by_alias=True, exclude_none=True)
    schema_json = json.dumps(payload, ensure_ascii=False, indent=1)
    return (
        _GUIDANCE
        + "\n\nDatabase schema (this batch):\n```json\n"
        + schema_json
        + "\n```\n\n"
        + "All table names in the full database (for cross-batch name awareness; "
        + "only draft classes for the tables in this batch's schema above):\n"
        + ", ".join(all_table_names)
        + "\n\n"
        + f"Target namespace: {namespace}\n"
        + f"Label language: {json.dumps(label_language)}\n"
    )
