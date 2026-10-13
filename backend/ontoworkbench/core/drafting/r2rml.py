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
import re
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


class R2rmlFinding(CamelModel):
    """One save-gate rejection (P2 spec §4.1). Empty list = save may proceed."""

    layer: int  # 1 syntax / 2 subset shape / 3 snapshot semantics
    message: str
    location: str | None = None


RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# Structural edges: map IRI → bnode. The predicate that points AT a bnode
# fixes its role; roles gate which predicates the bnode itself may carry.
_BNODE_ROLES = {
    f"{RR}logicalTable",
    f"{RR}subjectMap",
    f"{RR}predicateObjectMap",
    f"{RR}objectMap",
    f"{RR}joinCondition",
}
# Predicates allowed on each node kind ("" = the map IRI subject itself).
_ALLOWED_ON = {
    "": {f"{RR}logicalTable", f"{RR}subjectMap", f"{RR}predicateObjectMap"},
    f"{RR}logicalTable": {f"{RR}tableName"},
    f"{RR}subjectMap": {f"{RR}template", f"{RR}class"},
    f"{RR}predicateObjectMap": {f"{RR}predicate", f"{RR}objectMap"},
    f"{RR}objectMap": {
        f"{RR}column",
        f"{RR}datatype",
        f"{RR}parentTriplesMap",
        f"{RR}joinCondition",
    },
    f"{RR}joinCondition": {f"{RR}child", f"{RR}parent"},
}
# Literal-valued leaves; structural edges take bnodes; everything else on a
# bnode (predicate/class/datatype/parentTriplesMap) takes an IRI.
_LITERAL_LEAVES = {f"{RR}tableName", f"{RR}template", f"{RR}column", f"{RR}child", f"{RR}parent"}


def validate_r2rml(ttl: bytes, namespace: str, schema: SchemaModel | None) -> list[R2rmlFinding]:
    """Three-layer save gate (P2 spec §4.1).

    L1 Turtle syntax; L2 every quad accounted to the narrow subset shape
    (anti-superset: joins / logical tables / smuggled annotations reject);
    L3 snapshot semantics — columns referenced must exist, datatype must be
    an IRI. Skips L3 when the row predates snapshots (schema is None).

    Role routing is anti-superset, not full shape validation: a bnode shared
    by two structural edges is malformed input the gate may pass — the
    parse-back (browse view) then yields garbage, which is acceptable here.
    """
    # L1 — syntax (pyoxigraph surfaces parse errors as built-in SyntaxError).
    store = ox.Store()
    try:
        store.load(input=ttl, format=ox.RdfFormat.TURTLE, to_graph=ox.DefaultGraph())
    except SyntaxError as exc:
        return [R2rmlFinding(layer=1, message=f"Turtle 解析失败:{exc}")]
    quads = list(store)

    maps = {
        q.subject.value
        for q in quads
        if q.predicate.value == RDF_TYPE and q.object.value == f"{RR}TriplesMap"
    }
    # Role assignment is a bounded structural walk: the map IRI anchors
    # logicalTable/subjectMap/predicateObjectMap; objectMap nests under a
    # pom bnode and joinCondition under an objectMap bnode — three hops
    # deep in the narrow subset, so propagate until fixpoint (≤3 rounds).
    role: dict[str, str] = {}  # bnode id -> incoming structural predicate
    for _ in range(3):
        grew = False
        for q in quads:
            pv = q.predicate.value
            if pv not in _BNODE_ROLES or not isinstance(q.object, ox.BlankNode):
                continue
            if isinstance(q.subject, ox.NamedNode):
                anchored = q.subject.value in maps
            else:
                anchored = q.subject.value in role
            if anchored and q.object.value not in role:
                role[q.object.value] = pv
                grew = True
        if not grew:
            break

    findings: list[R2rmlFinding] = []
    for q in quads:
        s, pv, o = q.subject, q.predicate.value, q.object
        where = f"{s.value} {pv} {o.value}"
        if pv == RDF_TYPE:
            if o.value != f"{RR}TriplesMap" or s.value not in maps:
                findings.append(R2rmlFinding(layer=2, message="子集外的三元组", location=where))
            continue
        if isinstance(s, ox.NamedNode):
            ok = s.value in maps and pv in _ALLOWED_ON[""] and isinstance(o, ox.BlankNode)
        else:
            r = role.get(s.value)
            ok = r is not None and pv in _ALLOWED_ON[r]
            if ok:
                if pv in _LITERAL_LEAVES:
                    ok = isinstance(o, ox.Literal)
                elif pv in _BNODE_ROLES:
                    ok = isinstance(o, ox.BlankNode)
                elif pv == f"{RR}datatype":
                    # Spec files datatype under L3 — tag it before the
                    # generic IRI kind check can fail it into L2.
                    if not isinstance(o, ox.NamedNode):
                        findings.append(
                            R2rmlFinding(
                                layer=3,
                                message="datatype 必须是 IRI(如 xsd:string)",
                                location=where,
                            )
                        )
                        ok = False
                elif not isinstance(o, ox.NamedNode):
                    ok = False
                if ok and pv == f"{RR}parentTriplesMap" and o.value not in maps:
                    findings.append(
                        R2rmlFinding(
                            layer=2, message="parentTriplesMap 指向非 TriplesMap", location=where
                        )
                    )
                    ok = False
        if not ok:
            findings.append(R2rmlFinding(layer=2, message="子集外的三元组", location=where))
    if findings:
        return findings

    # L3 — snapshot semantics. Datatype-IRI rides the L2 walk above (kind
    # check re-tags it as layer 3 per the spec); column checks reuse the
    # parse-back model.
    if schema is None:
        return findings
    snap = {t.name: {c.name for c in t.columns} for t in schema.tables}

    def avail(table: str) -> str:
        return "、".join(sorted(snap.get(table, ())))

    for m in parse_r2rml(ttl, namespace):
        cols = snap.get(m.table)
        if cols is None:
            findings.append(R2rmlFinding(layer=3, message=f"表 {m.table} 不在映射快照中"))
            continue
        for ph in re.findall(r"\{([^{}]+)\}", m.subject_template):
            if ph not in cols:
                findings.append(
                    R2rmlFinding(
                        layer=3,
                        message=f"模板占位符 {{{ph}}} 不是表 {m.table} 的列;可用:{avail(m.table)}",
                    )
                )
        for p in m.column_props:
            if p.column not in cols:
                findings.append(
                    R2rmlFinding(
                        layer=3,
                        message=f"列 {m.table}.{p.column} 不存在;可用:{avail(m.table)}",
                    )
                )
        for fk in m.fk_props:
            if fk.child_column not in cols:
                findings.append(
                    R2rmlFinding(
                        layer=3,
                        message=f"列 {m.table}.{fk.child_column} 不存在;可用:{avail(m.table)}",
                    )
                )
            pcols = snap.get(fk.parent_table)
            if pcols is None:
                findings.append(
                    R2rmlFinding(layer=3, message=f"FK 父表 {fk.parent_table} 不在映射快照中")
                )
            elif fk.parent_column not in pcols:
                avail_parent = avail(fk.parent_table)
                msg = f"列 {fk.parent_table}.{fk.parent_column} 不存在;可用:{avail_parent}"
                findings.append(R2rmlFinding(layer=3, message=msg))
    return findings
