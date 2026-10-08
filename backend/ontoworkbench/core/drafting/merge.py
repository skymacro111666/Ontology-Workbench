"""Deterministic merger (spec §5.3 step 4 + §5.4 cascade rules).

Pure functions, milliseconds: batch DecisionSets → one MergedDraft; FK edges
nobody covered get default object properties; rejected classes cascade away
their properties and re-root their children; the TTL renderer writes the
blank_skeleton dialect of Turtle.
"""

from __future__ import annotations

from pydantic import Field

from ontoworkbench.core.drafting.models import (
    CamelModel,
    ClassDecision,
    DataPropertyDecision,
    DecisionSet,
    ObjectPropertyDecision,
    SchemaModel,
)


class MergedDraft(CamelModel):
    """The merged, cascade-safe drafting result (camelCase on the wire)."""

    classes: list[ClassDecision] = Field(default_factory=list)
    object_properties: list[ObjectPropertyDecision] = Field(default_factory=list)
    data_properties: list[DataPropertyDecision] = Field(default_factory=list)


def _pascal(name: str) -> str:
    """snake/camel → PascalCase."""
    return "".join(p.capitalize() for p in name.replace("-", "_").split("_") if p)


def merge_decisions(batches: list[DecisionSet], schema: SchemaModel) -> MergedDraft:
    """Merge batch outputs: class dedup, FK-edge completion, dedup properties."""
    draft = MergedDraft()
    seen_classes: set[str] = set()
    table_to_class: dict[str, str] = {}
    seen_obj: set[tuple[str, str]] = set()  # (name, domain) identity
    seen_data: set[tuple[str, str]] = set()
    covered_fks: set[str] = set()

    for batch in batches:
        for c in batch.classes:
            if c.name in seen_classes:
                continue
            seen_classes.add(c.name)
            draft.classes.append(c)
            table_to_class[c.source_table] = c.name
        for op in batch.object_properties:
            key = (op.name, op.domain)
            if key in seen_obj:
                continue
            seen_obj.add(key)
            draft.object_properties.append(op)
            covered_fks.add(op.source_fk)
        for dp in batch.data_properties:
            key = (dp.name, dp.domain)
            if key in seen_data:
                continue
            seen_data.add(key)
            draft.data_properties.append(dp)

    # FK completion: every schema edge whose both ends survived as classes and
    # that no LLM decision covered gets a deterministic default property
    # (spec §5.3: 跨批 FK 对象属性由合并器统一生成).
    used_names = {p.name for p in draft.object_properties}
    for table in schema.tables:
        domain = table_to_class.get(table.name)
        if domain is None:
            continue
        for fk in table.foreign_keys:
            source_fk = f"{table.name}.{fk.column}"
            if source_fk in covered_fks:
                continue
            range_ = table_to_class.get(fk.ref_table)
            if range_ is None:
                continue  # edge to a table whose class did not survive selection
            name = f"has{_pascal(fk.ref_table)}"
            if name in used_names:
                name = f"{domain}Has{range_}"
            used_names.add(name)
            draft.object_properties.append(
                ObjectPropertyDecision(
                    name=name, label=None, domain=domain, range=range_, source_fk=source_fk
                )
            )
    return draft


def apply_rejections(draft: MergedDraft, rejected: set[str]) -> None:
    """Cascade rejections in place (spec §5.4, user-ratified 2026-10-08).

    Dropping a class drops its data properties and every object property
    touching it; children re-root to their nearest surviving ancestor (or
    top level). Orphans are never kept.
    """
    # Snapshot the parent map before mutation for ancestor walks.
    parent_of = {c.name: c.parent_name for c in draft.classes}

    def nearest_surviving(cls: str) -> str | None:
        seen: set[str] = set()
        cur = parent_of.get(cls)
        while cur is not None and cur not in seen:
            if cur not in rejected:
                return cur
            seen.add(cur)
            cur = parent_of.get(cur)
        return None

    draft.classes = [c for c in draft.classes if c.name not in rejected]
    for c in draft.classes:
        if c.parent_name is not None and c.parent_name in rejected:
            c.parent_name = nearest_surviving(c.name)
    draft.object_properties = [
        p for p in draft.object_properties if p.domain not in rejected and p.range not in rejected
    ]
    draft.data_properties = [p for p in draft.data_properties if p.domain not in rejected]


def _esc(s: str) -> str:
    """Turtle literal escaping (blank_skeleton dialect)."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_ttl(
    draft: MergedDraft, namespace: str, prefix: str, title: str, label_language: str = "zh"
) -> bytes:
    """Serialize the draft as Turtle (blank_skeleton style, hand-rolled)."""
    onto_iri = namespace.rstrip("#/")
    lines = [
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        f"@prefix {prefix}: <{namespace}> .",
        "",
        f"<{onto_iri}> a owl:Ontology ;",
        f'    rdfs:label "{_esc(title)}" ;',
        f'    dcterms:title "{_esc(title)}" .',
        "",
    ]
    for c in draft.classes:
        stmts = [
            f"{prefix}:{c.name} a owl:Class",
            f'    rdfs:label "{_esc(c.label)}"@{label_language}',
        ]
        if c.comment:
            stmts.append(f'    rdfs:comment "{_esc(c.comment)}"@{label_language}')
        if c.parent_name:
            stmts.append(f"    rdfs:subClassOf {prefix}:{c.parent_name}")
        lines.append(" ;\n".join(stmts) + " .")
        lines.append("")
    for op in draft.object_properties:
        stmts = [
            f"{prefix}:{op.name} a owl:ObjectProperty",
            f"    rdfs:domain {prefix}:{op.domain}",
            f"    rdfs:range {prefix}:{op.range}",
        ]
        if op.label:
            stmts.append(f'    rdfs:label "{_esc(op.label)}"@{label_language}')
        lines.append(" ;\n".join(stmts) + " .")
        lines.append("")
    for dp in draft.data_properties:
        stmts = [
            f"{prefix}:{dp.name} a owl:DatatypeProperty",
            f"    rdfs:domain {prefix}:{dp.domain}",
            f"    rdfs:range {dp.datatype}",
        ]
        if dp.label:
            stmts.append(f'    rdfs:label "{_esc(dp.label)}"@{label_language}')
        lines.append(" ;\n".join(stmts) + " .")
        lines.append("")
    return "\n".join(lines).encode()
