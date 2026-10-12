"""R2RML serialization of a drafted ontology (R2RML P1 spec §4.1).

Narrow subset: one TriplesMap per kept class (logicalTable = tableName),
row identity from the PK (multi-column concatenated with "/"; single-column
UNIQUE fallback; else the table is skipped and listed), data properties as
column POMs, FK-derived object properties as refObjectMaps. Hand-rolled
render following merge.render_ttl; parse_r2rml reads our own output back
into structured models for the browse view (round-trip is tested).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

import pyoxigraph as ox
from pydantic import Field

from .merge import MergedDraft, _esc
from .models import CamelModel, SchemaModel, TableSpec
from .pipeline import _prefix_for

RR = "http://www.w3.org/ns/r2rml#"
XSD = "http://www.w3.org/2001/XMLSchema#"


@dataclass
class RenderedR2rml:
    """Serializer output: the Turtle document plus tables left out."""

    ttl: bytes
    skipped_tables: list[str] = field(default_factory=list)


class R2rmlColumnProp(CamelModel):
    """One column → data-property predicate-object map."""

    predicate: str
    column: str
    datatype: str


class R2rmlFkProp(CamelModel):
    """One FK → object-property refObjectMap with its join."""

    predicate: str
    child_column: str
    parent_table: str
    parent_column: str


class R2rmlTriplesMap(CamelModel):
    """One parsed TriplesMap (parse_r2rml output; browse-view model)."""

    table: str
    class_name: str
    subject_template: str
    column_props: list[R2rmlColumnProp] = Field(default_factory=list)
    fk_props: list[R2rmlFkProp] = Field(default_factory=list)


def _identity_columns(table: TableSpec) -> list[str]:
    """Row identity: PK columns (any count) > single UNIQUE column > none."""
    pk = [c.name for c in table.columns if c.primary_key]
    if pk:
        return pk
    uniq = [c.name for c in table.columns if c.unique]
    return uniq if len(uniq) == 1 else []


def schema_hash(schema: SchemaModel) -> str:
    """Stable hash of the *selected* schema subset, reflection-order free.

    P3 drift detection compares this against a fresh reflect — columns the
    user never selected must not flip it, so it hashes the subset only.
    """
    canon = schema.model_dump(by_alias=True)
    for t in canon["tables"]:
        t["columns"].sort(key=lambda c: c["name"])
        t["foreignKeys"].sort(key=lambda f: f["column"])
    canon["tables"].sort(key=lambda t: t["name"])
    return hashlib.sha256(
        json.dumps(canon, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def render_r2rml(draft: MergedDraft, schema: SchemaModel, namespace: str) -> RenderedR2rml:
    """Serialize the kept decisions as narrow-subset R2RML Turtle."""
    onto_iri = namespace.rstrip("#/")
    prefix = _prefix_for(schema.database_name)
    tables = {t.name: t for t in schema.tables}

    skipped: list[str] = []
    idents: dict[str, list[str]] = {}  # table -> identity columns
    for cls in draft.classes:
        table = tables.get(cls.source_table)
        cols = _identity_columns(table) if table else []
        if not cols:
            skipped.append(cls.source_table)
        else:
            idents[cls.source_table] = cols
    live = {c.name for c in draft.classes if c.source_table in idents}

    def map_iri(class_name: str) -> str:
        return f"{onto_iri}/r2rml/{class_name}"

    blocks: list[str] = []
    for cls in draft.classes:
        if cls.source_table not in idents:
            continue
        table = tables[cls.source_table]
        # R2RML templates reference identity columns as {col} placeholders.
        tmpl = "/".join(
            [onto_iri, cls.source_table, *(f"{{{c}}}" for c in idents[cls.source_table])]
        )
        # Every line carries its own terminator; the block-level trailing
        # " ;" is swapped for " ." at the end (empty-POM maps close here too).
        lines = [
            f"<{map_iri(cls.name)}> a rr:TriplesMap ;",
            f'    rr:logicalTable [ rr:tableName "{_esc(cls.source_table)}" ] ;',
            "    rr:subjectMap [",
            f'        rr:template "{_esc(tmpl)}" ;',
            f"        rr:class {prefix}:{cls.name} ;",
            "    ] ;",
        ]
        for dp in draft.data_properties:
            if dp.domain != cls.name or dp.domain not in live:
                continue
            col = dp.source_column.split(".", 1)[1]
            lines += [
                "    rr:predicateObjectMap [",
                f"        rr:predicate {prefix}:{dp.name} ;",
                f'        rr:objectMap [ rr:column "{_esc(col)}" ; rr:datatype {dp.datatype} ] ;',
                "    ] ;",
            ]
        for op in draft.object_properties:
            if op.domain != cls.name or op.domain not in live or op.range not in live:
                continue  # 引用表被跳过 → refObjectMap 会悬空,不渲染
            fk_col = op.source_fk.split(".", 1)[1]
            fk = next((f for f in table.foreign_keys if f.column == fk_col), None)
            if fk is None:
                continue
            lines += [
                "    rr:predicateObjectMap [",
                f"        rr:predicate {prefix}:{op.name} ;",
                "        rr:objectMap [",
                f"            rr:parentTriplesMap <{map_iri(op.range)}> ;",
                f'            rr:joinCondition [ rr:child "{_esc(fk.column)}" ;'
                f' rr:parent "{_esc(fk.ref_column)}" ] ;',
                "        ] ;",
                "    ] ;",
            ]
        blocks.append("\n".join(lines).removesuffix(" ;") + " .")

    header = (
        "@prefix rr: <http://www.w3.org/ns/r2rml#> .\n"
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n"
        f"@prefix {prefix}: <{namespace}> .\n"
    )
    body = ("\n\n".join(blocks) + "\n") if blocks else ""
    return RenderedR2rml(ttl=(header + "\n" + body).encode(), skipped_tables=skipped)


def parse_r2rml(ttl: bytes, namespace: str) -> list[R2rmlTriplesMap]:
    """Read our own narrow output back into structured models (browse view).

    Not a general R2RML parser: only the shapes render_r2rml emits. Blank
    nodes correlate by id within one Store load; map IRIs are the absolute
    <{onto_iri}/r2rml/{Class}> form the renderer writes.
    """
    onto_iri = namespace.rstrip("#/")
    store = ox.Store()
    store.load(input=ttl, format=ox.RdfFormat.TURTLE, to_graph=ox.DefaultGraph())

    def local(iri: str) -> str:
        return iri[len(namespace) :] if iri.startswith(namespace) else iri

    def xsd_local(iri: str) -> str:
        return "xsd:" + iri[len(XSD) :] if iri.startswith(XSD) else iri

    # One pass, buckets: blank-node literal props, blank-node→blank-node
    # refs, and TriplesMap-level edges (logicalTable/subjectMap keyed by the
    # map IRI, predicateObjectMap as an ordered list).
    bprops: dict[str, dict[str, str]] = {}
    brefs: dict[str, dict[str, str]] = {}
    mprops: dict[str, dict[str, str]] = {}  # map iri -> {"a": rr:TriplesMap}
    mrefs: dict[str, dict[str, str]] = {}
    mpoms: dict[str, list[str]] = {}
    for quad in store:
        s, p, o = quad.subject, quad.predicate, quad.object
        pv, ov = p.value, o.value  # .value: IRI / lexical form / bnode id
        if isinstance(s, ox.BlankNode):
            (brefs if isinstance(o, ox.BlankNode) else bprops).setdefault(s.value, {})[pv] = ov
        elif s.value.startswith(f"{onto_iri}/r2rml/"):
            if isinstance(o, ox.BlankNode):
                if pv == f"{RR}predicateObjectMap":
                    mpoms.setdefault(s.value, []).append(ov)
                else:  # logicalTable / subjectMap
                    mrefs.setdefault(s.value, {})[pv] = ov
            else:
                mprops.setdefault(s.value, {})[pv] = ov

    def table_of(map_iri: str) -> str:
        return bprops[mrefs[map_iri][f"{RR}logicalTable"]][f"{RR}tableName"]

    out: list[R2rmlTriplesMap] = []
    # pyoxigraph's Store iterates in internal canonical order, not document
    # order — sort map IRIs (shared prefix ⇒ class-name order) for determinism.
    for map_iri in sorted(mprops):
        # subjectMap children (template literal / class IRI) live in bprops;
        # only blank→blank edges (subjectMap itself) ride brefs/mrefs.
        subj = bprops[mrefs[map_iri][f"{RR}subjectMap"]]
        cols: list[R2rmlColumnProp] = []
        fks: list[R2rmlFkProp] = []
        for pom in mpoms.get(map_iri, []):
            predicate = local(bprops[pom][f"{RR}predicate"])
            om = brefs[pom][f"{RR}objectMap"]
            oprops = bprops.get(om, {})
            if f"{RR}column" in oprops:
                cols.append(
                    R2rmlColumnProp(
                        predicate=predicate,
                        column=oprops[f"{RR}column"],
                        datatype=xsd_local(oprops[f"{RR}datatype"]),
                    )
                )
            else:
                parent = bprops[om][f"{RR}parentTriplesMap"]  # NamedNode → bprops
                jc = brefs[om][f"{RR}joinCondition"]  # blank→blank edge
                fks.append(
                    R2rmlFkProp(
                        predicate=predicate,
                        child_column=bprops[jc][f"{RR}child"],
                        parent_table=table_of(parent),
                        parent_column=bprops[jc][f"{RR}parent"],
                    )
                )
        out.append(
            R2rmlTriplesMap(
                table=table_of(map_iri),
                class_name=local(subj[f"{RR}class"]),
                subject_template=subj[f"{RR}template"],
                column_props=cols,
                fk_props=fks,
            )
        )
    return out
