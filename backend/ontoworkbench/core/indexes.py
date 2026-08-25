"""In-memory derived indexes over IR: tree/search/neighbors/overview."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ontoworkbench.core.ir import EntityIR, IRBundle

MAX_OVERVIEW_NODES = 5000

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
    def search(self, q: str, limit: int = 20) -> list[SearchHit]:
        """Case-insensitive substring search over localname/label/comment."""
        ql = q.lower()
        hits: list[SearchHit] = []
        for e in sorted(self._ir.entities.values(), key=lambda x: x.curie):
            local = e.curie.split(":")[-1].lower()
            if ql in local:
                field = "localname"
            elif any(ql in v.lower() for v in e.label.values()):
                field = "label"
            elif e.comment and ql in e.comment.lower():
                field = "comment"
            else:
                continue
            hits.append(
                SearchHit(eid=e.eid, curie=e.curie, label=e.label, type=e.type, matched_field=field)
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


def build_indexes(ir: IRBundle) -> Indexes:
    """Factory kept for API symmetry with build_ir."""
    return Indexes(ir)
