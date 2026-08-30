"""In-memory derived indexes over IR: tree/search/neighbors/overview."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ontoworkbench.core.ir import EntityIR, IndividualIR, IRBundle

MAX_OVERVIEW_NODES = 5000

# xsd namespace: range rows landing here are datatypes, not declared classes.
XSD_NS = "http://www.w3.org/2001/XMLSchema#"

# Sentinel parent for the sidebar's property tab: tree(parent=__props__)
# lists property entities (eids are full IRIs, so this cannot collide).
PROPS_PARENT = "__props__"


class TreeNode(BaseModel):
    """One node of the lazily-loaded class/property tree."""

    eid: str
    curie: str
    label: dict[str, str] = {}
    type: str = "Class"
    children_count: int = 0
    instance_count: int = 0


class SearchHit(BaseModel):
    """One search result with the field that matched."""

    eid: str
    curie: str
    label: dict[str, str] = {}
    type: str
    matched_field: str


class SchemaTarget(BaseModel):
    """An assertion property's far end: a class or an xsd datatype."""

    kind: str  # class | datatype
    curie: str
    eid: str | None = None
    declared: bool | None = None


class SchemaProp(BaseModel):
    """One usable assertion property for a set of classes (spec §4.1)."""

    eid: str
    curie: str
    label: dict[str, str] = {}
    ptype: str
    inherited: bool = False
    via: str | None = None  # curie of the class pulling it in (inherited only)
    target: SchemaTarget | None = None


class Indexes:
    """Derived, immutable after build; cheap lookups for all read APIs."""

    def __init__(self, ir: IRBundle) -> None:
        """Index the bundle: parent-eid → children map built once."""
        self._ir = ir
        self._children: dict[str, list[EntityIR]] = {}
        for e in ir.entities.values():
            for p in e.parents:
                self._children.setdefault(p.eid, []).append(e)
        for kids in self._children.values():
            kids.sort(key=lambda x: x.curie)

    def _roots(self) -> list[EntityIR]:
        # A class whose parents are all external (undeclared) is its own root —
        # otherwise it would hang off a parent no walk ever visits.
        return sorted(
            (
                e
                for e in self._ir.entities.values()
                if e.type == "Class" and not any(p.eid in self._ir.entities for p in e.parents)
            ),
            key=lambda x: x.curie,
        )

    def entity(self, eid: str) -> EntityIR | None:
        """Look up one entity by eid (full IRI)."""
        return self._ir.entities.get(eid)

    # -- individuals ------------------------------------------------------
    @property
    def ir(self) -> IRBundle:
        """The underlying bundle (lint / schema walks need more than lookups)."""
        return self._ir

    def individual(self, eid: str) -> IndividualIR | None:
        """Look up one named individual by eid (full IRI)."""
        return self._ir.individuals.get(eid)

    # -- tree -----------------------------------------------------------
    def tree(self, parent_eid: str | None) -> list[TreeNode]:
        """Direct children of parent (or roots when None).

        PROPS_PARENT is the sentinel for the sidebar's property tab:
        it lists property entities with the same lazy-loading semantics.
        """
        if parent_eid is None:
            items: list[EntityIR] = self._roots()
        elif parent_eid == PROPS_PARENT:
            items = sorted(
                (e for e in self._ir.entities.values() if e.type != "Class"),
                key=lambda x: x.curie,
            )
        else:
            items = self._children.get(parent_eid, [])
        return [
            TreeNode(
                eid=e.eid,
                curie=e.curie,
                label=e.label,
                type=e.type,
                children_count=len(self._children.get(e.eid, [])),
                instance_count=len(self._ir.instances.get(e.eid, [])),
            )
            for e in items
        ]

    # -- search ---------------------------------------------------------
    def search(self, q: str, limit: int = 20, type_: str | None = None) -> list[SearchHit]:
        """Case-insensitive substring search over localname/label/comment.

        Individuals join with type='Instance' (localname/label only); type_
        filters to one entity type ('Instance' picks individuals).
        """
        ql = q.lower()
        hits: list[SearchHit] = []

        def _match(curie: str, label: dict[str, str], comment: str | None) -> str | None:
            if ql in curie.split(":")[-1].lower():
                return "localname"
            if any(ql in v.lower() for v in label.values()):
                return "label"
            if comment and ql in comment.lower():
                return "comment"
            return None

        for e in sorted(self._ir.entities.values(), key=lambda x: x.curie):
            if type_ and e.type != type_:
                continue
            field = _match(e.curie, e.label, e.comment)
            if field:
                hits.append(
                    SearchHit(
                        eid=e.eid, curie=e.curie, label=e.label, type=e.type, matched_field=field
                    )
                )
                if len(hits) >= limit:
                    return hits
        if type_ and type_ != "Instance":
            return hits
        for ind in sorted(self._ir.individuals.values(), key=lambda x: x.curie):
            field = _match(ind.curie, ind.label, None)
            if field:
                hits.append(
                    SearchHit(
                        eid=ind.eid,
                        curie=ind.curie,
                        label=ind.label,
                        type="Instance",
                        matched_field=field,
                    )
                )
                if len(hits) >= limit:
                    break
        return hits

    # -- graph ----------------------------------------------------------
    def neighbors(self, eid: str) -> dict[str, Any]:
        """Nodes/edges for the local view: parents, children, siblings, props."""
        e = self._ir.entities[eid]
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[dict[str, str]] = []

        def add(uri: str, kind: str) -> None:
            ent = self._ir.entities.get(uri)
            if ent:
                nodes[uri] = {
                    "id": uri,
                    "curie": ent.curie,
                    "label": ent.label,
                    "kind": kind,
                }

        add(eid, "self")
        for p in e.parents:
            add(p.eid, "class")
            edges.append({"source": eid, "target": p.eid, "kind": "subClassOf"})
        for c in self._children.get(eid, []):
            add(c.eid, "class")
            edges.append({"source": c.eid, "target": eid, "kind": "subClassOf"})
        for p in e.parents:  # siblings
            for s in self._children.get(p.eid, []):
                if s.eid != eid:
                    add(s.eid, "class")
                    edges.append({"source": s.eid, "target": p.eid, "kind": "subClassOf"})
        for prop in e.properties:
            add(prop.eid, "property")
            edges.append({"source": eid, "target": prop.eid, "kind": "property"})
        return {"nodes": list(nodes.values()), "edges": edges}

    def instances(self, eid: str) -> dict[str, Any]:
        """A class's direct named individuals as a canvas-shaped payload.

        Instances join the graph only on demand (badge click), each linked
        to its class with an 'instance' edge.
        """
        insts = self._ir.instances.get(eid, [])
        return {
            "nodes": [
                {"id": i.eid, "curie": i.curie, "label": i.label, "kind": "instance"} for i in insts
            ],
            "edges": [{"source": i.eid, "target": eid, "kind": "instance"} for i in insts],
        }

    def overview(self, max_nodes: int = MAX_OVERVIEW_NODES) -> dict[str, Any]:
        """Whole-graph view: full hierarchy within max_nodes, top-3 levels past it.

        Past the budget (truncated) wide-but-shallow graphs still blow past
        max_nodes inside 3 levels, so the budget caps rendered nodes as well.
        """
        roots = self._roots()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        budget = max_nodes
        # Degrade to the top 3 levels only past the node budget (spec §7.5);
        # under it the hierarchy renders at full depth.
        depth_cap = 3 if len(self._ir.entities) > max_nodes else None
        # Multi-parent entities are reachable through several roots/branches —
        # they must still land in `nodes` once (canvas keys nodes by id), while
        # every walked parent link keeps its edge.
        seen: set[str] = set()

        def walk(e: EntityIR, depth: int) -> int:
            nonlocal budget
            if budget <= 0 or e.eid in seen:
                return 0
            seen.add(e.eid)
            nodes.append(
                {
                    "id": e.eid,
                    "curie": e.curie,
                    "label": e.label,
                    "kind": "class",
                    "instance_count": len(self._ir.instances.get(e.eid, [])),
                }
            )
            budget -= 1
            count = 1
            if depth_cap is None or depth < depth_cap:
                for c in self._children.get(e.eid, []):
                    if budget <= 0:
                        break
                    edges.append({"source": c.eid, "target": e.eid, "kind": "subClassOf"})
                    count += walk(c, depth + 1)
            return count

        for r in roots:
            if budget <= 0:
                break
            walk(r, 0)

        # Properties join the canvas after the class tree (spec §7.3): each
        # property entity renders once, linked to every rendered class it
        # constrains via domain/range; DatatypeProperty reads as 'datatype'
        # (dotted), every other property as 'property' (solid).
        prop_nodes: dict[str, dict[str, Any]] = {}
        for e in self._ir.entities.values():
            if budget <= 0:
                break
            if e.type != "Class" or e.eid not in seen:
                continue
            linked: set[str] = set()
            for prop in e.properties:
                if prop.eid in linked:
                    continue
                linked.add(prop.eid)
                if prop.eid not in prop_nodes:
                    if budget <= 0:
                        break
                    prop_nodes[prop.eid] = {
                        "id": prop.eid,
                        "curie": prop.curie,
                        "label": prop.label,
                        "kind": "property",
                        "ptype": prop.ptype,
                    }
                    budget -= 1
                kind = "datatype" if prop.ptype == "DatatypeProperty" else "property"
                edges.append({"source": e.eid, "target": prop.eid, "kind": kind})
        nodes.extend(prop_nodes.values())

        return {
            "nodes": nodes,
            "edges": edges,
            "truncated": depth_cap is not None,
            "total_count": len(self._ir.entities),
        }

    # -- assertion schema / edges ----------------------------------------
    def assertion_schema(self, class_eids: list[str]) -> list[SchemaProp]:
        """Usable assertion properties: superclass-closure domains plus domainless (spec §3)."""
        direct = {e for e in class_eids if e in self._ir.entities}
        closure: set[str] = set()
        stack = list(direct)
        while stack:
            eid = stack.pop()
            if eid in closure or eid not in self._ir.entities:
                continue
            closure.add(eid)
            stack.extend(p.eid for p in self._ir.entities[eid].parents)
        out: dict[str, SchemaProp] = {}
        for e in sorted(self._ir.entities.values(), key=lambda x: x.curie):
            if e.type == "Class":
                continue
            domains = [r for r in e.referenced_by if r.relation == "rdfs:domain"]
            if domains:
                hit = next((r for r in domains if r.eid in closure), None)
                if hit is None:
                    continue
                inherited = hit.eid not in direct
                via = hit.curie if inherited else None
            else:
                inherited, via = False, None  # domainless: universal
            ranges = [r for r in e.referenced_by if r.relation == "rdfs:range"]
            target = None
            if ranges:
                r0 = ranges[0]
                is_dt = r0.eid is None or r0.eid.startswith(XSD_NS)
                target = SchemaTarget(
                    kind="datatype" if is_dt else "class",
                    curie=r0.curie,
                    eid=r0.eid,
                    declared=None if is_dt else (r0.eid in self._ir.entities),
                )
            out[e.eid] = SchemaProp(
                eid=e.eid,
                curie=e.curie,
                label=e.label,
                ptype=e.type,
                inherited=inherited,
                via=via,
                target=target,
            )
        return list(out.values())

    def assertion_edges(self, eids: list[str]) -> dict[str, object]:
        """Object assertions whose BOTH ends are in the given set (cap 500)."""
        want = set(eids)
        edges: list[dict[str, str]] = []
        for eid in sorted(want):
            ind = self._ir.individuals.get(eid)
            if not ind:
                continue
            for a in ind.object_assertions:
                if a.object.eid in want:
                    edges.append(
                        {
                            "source": eid,
                            "target": a.object.eid,
                            "label": a.property.curie.split(":")[-1],
                        }
                    )
                    if len(edges) >= 500:
                        return {"edges": edges, "truncated": True, "total": len(edges) + 1}
        return {"edges": edges, "truncated": False, "total": len(edges)}


def build_indexes(ir: IRBundle) -> Indexes:
    """Factory kept for API symmetry with build_ir."""
    return Indexes(ir)
