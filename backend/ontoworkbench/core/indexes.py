"""In-memory derived indexes over IR: tree/search/neighbors/overview."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ontoworkbench.core.ir import EntityIR, IRBundle

MAX_OVERVIEW_NODES = 500


class TreeNode(BaseModel):
    """One node of the lazily-loaded class tree."""

    eid: str
    curie: str
    label: dict[str, str] = {}
    children_count: int = 0


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
        return sorted(
            (e for e in self._ir.entities.values() if e.type == "Class" and not e.parents),
            key=lambda x: x.curie,
        )

    # -- tree -----------------------------------------------------------
    def tree(self, parent_eid: str | None) -> list[TreeNode]:
        """Direct children of parent (or roots when None)."""
        if parent_eid is None:
            items: list[EntityIR] = self._roots()
        else:
            items = self._children.get(parent_eid, [])
        return [
            TreeNode(
                eid=e.eid,
                curie=e.curie,
                label=e.label,
                children_count=len(self._children.get(e.eid, [])),
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

    def overview(self, max_nodes: int = MAX_OVERVIEW_NODES) -> dict[str, Any]:
        """Whole-graph view, bounded: top-3 levels and at most max_nodes rendered.

        Wide-but-shallow graphs would blow past max_nodes inside 3 levels,
        so the budget caps rendered nodes as well (truncated reflects either cut).
        """
        roots = self._roots()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        budget = max_nodes

        def walk(e: EntityIR, depth: int) -> int:
            nonlocal budget
            if budget <= 0:
                return 0
            nodes.append({"id": e.eid, "curie": e.curie, "label": e.label, "kind": "class"})
            budget -= 1
            count = 1
            if depth < 3:
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
        truncated = len(self._ir.entities) > max_nodes
        return {
            "nodes": nodes,
            "edges": edges,
            "truncated": truncated,
            "total_count": len(self._ir.entities),
        }


def build_indexes(ir: IRBundle) -> Indexes:
    """Factory kept for API symmetry with build_ir."""
    return Indexes(ir)
