"""In-memory derived indexes over IR: tree/search/neighbors/overview."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from ontoworkbench.core.ir import EntityIR, IndividualIR, IRBundle
from ontoworkbench.core.terms import XSD_NS

MAX_OVERVIEW_NODES = 5000

# Payload cap for assertion-edges: totals stay truthful, only the list is cut.
MAX_ASSERTION_EDGES = 500

# Sentinel parent for the sidebar's property tab: tree(parent=__props__)
# lists property entities (eids are full IRIs, so this cannot collide).
PROPS_PARENT = "__props__"

# Progressive canvas (spec §4/§5): the deprecated bucket browses every
# owl:deprecated class in one flat list, capped per expand call.
DEPRECATED_BUCKET = "__deprecated__"
DEPRECATED_EXPAND_CAP = 500

# Tiering (spec §3): ≤1000 live classes the full view serves as-is (doc-only
# tier, no code branch); ≤2000 still full; past it overview auto-switches to
# the folded root view. More isolated roots than PREFIX_BUCKET_ROOTS group by
# curie prefix instead of flooding the canvas.
PROGRESSIVE_THRESHOLD = 2000
PREFIX_BUCKET_ROOTS = 50


class TreeNode(BaseModel):
    """One node of the lazily-loaded class/property tree."""

    eid: str
    curie: str
    label: dict[str, str] = {}
    type: str = "Class"
    children_count: int = 0
    instance_count: int = 0
    deprecated: bool = False


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
        # list(...) snapshots before iterating: refresh_entities may patch the
        # shared bundle mid-build (GIL makes list() atomic), so a concurrent
        # refresh cannot raise "dictionary changed size during iteration".
        for e in list(ir.entities.values()):
            for p in e.parents:
                self._children.setdefault(p.eid, []).append(e)
        for kids in self._children.values():
            kids.sort(key=lambda x: x.curie)
        self._subtree: dict[str, int] = {}
        self._recount_subtree()

    def _recount_subtree(self) -> None:
        """Memoized subtree size per class, live-only (存活口径, 2026-09-07).

        Deprecated children never count — the canvas cannot unfold them
        (spec §4), so a fold badge's number equals what a full unfold would
        actually produce.

        A full recount after every incremental patch stays cheap (52k classes
        ~50ms) and can never disagree with the patched children map, so the
        simple always-recompute beats surgical memo eviction.
        """
        self._subtree = {}

        def _count(eid: str) -> int:
            if eid in self._subtree:
                return self._subtree[eid]
            self._subtree[eid] = 1  # cycle guard: counts itself even in a loop
            self._subtree[eid] = 1 + sum(
                _count(c.eid) for c in self._children.get(eid, []) if not c.deprecated
            )
            return self._subtree[eid]

        for e in list(self._ir.entities.values()):
            if e.type == "Class":
                _count(e.eid)

    def subtree_size(self, eid: str) -> int:
        """子树大小(含自身);未知 eid 返回 1。."""
        return self._subtree.get(eid, 1)

    def expand(
        self, eid: str, include_deprecated: bool = False, cap: int = DEPRECATED_EXPAND_CAP
    ) -> dict[str, Any]:
        """下钻取数:某类的直接子类(带子树大小),或废弃桶/前缀桶的分页浏览。."""
        if eid.startswith("__prefix__:"):
            # A prefix bucket from the progressive overview: list that
            # prefix's root classes (each still foldable via its own expand).
            prefix = eid.split(":", 1)[1]
            roots = [
                r for r in self._roots(True) if (r.curie.split(":", 1)[0] or "(default)") == prefix
            ]
            nodes = [
                {
                    "id": r.eid,
                    "curie": r.curie,
                    "label": r.label,
                    "kind": "class",
                    "instanceCount": len(self._ir.instances.get(r.eid, [])),
                    "subtreeSize": self.subtree_size(r.eid),
                    # 存活子树 >1 ⟺ 存在可展开的存活子类,叶子根不画角标。
                    "folded": self.subtree_size(r.eid) > 1,
                    "deprecated": r.deprecated,
                }
                for r in roots[:cap]
            ]
            return {
                "nodes": nodes,
                "edges": [],
                "truncated": len(roots) > cap,
                "totalCount": len(roots),
            }
        if eid == DEPRECATED_BUCKET:
            deps = sorted(
                (e for e in list(self._ir.entities.values()) if e.type == "Class" and e.deprecated),
                key=lambda x: x.curie,
            )
            nodes = [
                {
                    "id": e.eid,
                    "curie": e.curie,
                    "label": e.label,
                    "kind": "class",
                    "instanceCount": len(self._ir.instances.get(e.eid, [])),
                    "subtreeSize": 1,
                    # A deprecated class may still have live children worth
                    # unfolding; most are leaves (deprecation unlinks them).
                    "folded": self.subtree_size(e.eid) > 1,
                    "deprecated": True,
                }
                for e in deps[:cap]
            ]
            return {
                "nodes": nodes,
                "edges": [],
                "truncated": len(deps) > cap,
                "totalCount": len(deps),
            }
        # Unknown eid → the route layer already _entity_or_404'd it; assert
        # here so a registration gap cannot silently render an empty canvas.
        assert self.entity(eid) is not None, f"expand on unknown eid {eid}"
        kids = [c for c in self._children.get(eid, []) if include_deprecated or not c.deprecated]
        nodes = [
            {
                "id": c.eid,
                "curie": c.curie,
                "label": c.label,
                "kind": "class",
                "instanceCount": len(self._ir.instances.get(c.eid, [])),
                "subtreeSize": self.subtree_size(c.eid),
                # Foldability follows the live subtree (存活口径): a child with
                # only deprecated children must not render an empty-unfold
                # badge — its expand payload would come back childless.
                "folded": self.subtree_size(c.eid) > 1,
                "deprecated": c.deprecated,
            }
            for c in kids[:cap]
        ]
        edges = [{"source": c.eid, "target": eid, "kind": "subClassOf"} for c in kids[:cap]]
        return {
            "nodes": nodes,
            "edges": edges,
            "truncated": len(kids) > cap,
            "totalCount": len(kids),
        }

    def rebuild_children_of(self, eids: Iterable[str]) -> None:
        """增量编辑后按 ir 实体当前 children 重建 _children 行(整列表原子替换)。."""
        for parent in eids:
            e = self._ir.entities.get(parent)
            if e is None:
                self._children.pop(parent, None)
                continue
            kids = [self._ir.entities[c.eid] for c in e.children if c.eid in self._ir.entities]
            if kids:
                self._children[parent] = sorted(kids, key=lambda x: x.curie)
            else:
                self._children.pop(parent, None)
        # Fold badges read subtree sizes; a patched children map invalidates
        # them all, so recount (cheap and always right, see _recount_subtree).
        self._recount_subtree()

    def _roots(self, include_deprecated: bool = False) -> list[EntityIR]:
        # A class whose parents are all external (undeclared) is its own root —
        # otherwise it would hang off a parent no walk ever visits.
        # Deprecated classes sit at root level by OBO convention (deprecation
        # unlinks them from the hierarchy), so they starve the node budget
        # unless explicitly asked for (spec §4).
        return sorted(
            (
                e
                for e in list(self._ir.entities.values())
                if e.type == "Class"
                and (include_deprecated or not e.deprecated)
                and not any(p.eid in self._ir.entities for p in e.parents)
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
    def tree(self, parent_eid: str | None, include_deprecated: bool = False) -> list[TreeNode]:
        """Direct children of parent (or roots when None).

        PROPS_PARENT is the sentinel for the sidebar's property tab:
        it lists property entities with the same lazy-loading semantics.
        Deprecated classes are hidden unless include_deprecated (spec §4).
        """
        if parent_eid is None:
            items: list[EntityIR] = self._roots(include_deprecated)
        elif parent_eid == PROPS_PARENT:
            items = sorted(
                (e for e in list(self._ir.entities.values()) if e.type != "Class"),
                key=lambda x: x.curie,
            )
        elif parent_eid == DEPRECATED_BUCKET:
            # The sidebar's deprecated tab: every deprecated class, flat.
            # The request itself is the intent, so include_deprecated is moot.
            items = sorted(
                (e for e in list(self._ir.entities.values()) if e.type == "Class" and e.deprecated),
                key=lambda x: x.curie,
            )
        else:
            items = sorted(
                (
                    e
                    for e in self._children.get(parent_eid, [])
                    if include_deprecated or not e.deprecated
                ),
                key=lambda x: x.curie,
            )
        return [
            TreeNode(
                eid=e.eid,
                curie=e.curie,
                label=e.label,
                type=e.type,
                children_count=len(self._children.get(e.eid, [])),
                instance_count=len(self._ir.instances.get(e.eid, [])),
                deprecated=e.deprecated,
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

        for e in sorted(list(self._ir.entities.values()), key=lambda x: x.curie):
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

    def overview(
        self,
        max_nodes: int = MAX_OVERVIEW_NODES,
        include_deprecated: bool = False,
        view: str = "auto",
    ) -> dict[str, Any]:
        """Whole-graph view, tiered by live-class count (spec §3).

        auto: full walk within PROGRESSIVE_THRESHOLD live classes, folded
        root view past it; view='full' forces the legacy walk (then the
        max_nodes budget truncates), view='progressive' forces folding.
        Deprecated classes are excluded unless include_deprecated (spec §4);
        deprecatedCount reports how many are hidden this way.
        """
        live = sum(1 for e in list(self._ir.entities.values()) if not e.deprecated)
        progressive = view != "full" and (view == "progressive" or live > PROGRESSIVE_THRESHOLD)
        base: dict[str, Any] = {
            "mode": "progressive" if progressive else "full",
            "liveCount": live,
            "deprecatedCount": sum(
                1 for e in list(self._ir.entities.values()) if e.type == "Class" and e.deprecated
            ),
        }
        if progressive:
            return {
                **base,
                **self._progressive_payload(include_deprecated),
                "truncated": False,
                "total_count": len(self._ir.entities),
            }
        roots = self._roots(include_deprecated)
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
            if not include_deprecated and e.deprecated:
                return 0
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
                    # Filter before the edge: a subClassOf edge whose child
                    # never renders would dangle and crash the id-keyed canvas.
                    if not include_deprecated and c.deprecated:
                        continue
                    edges.append({"source": c.eid, "target": e.eid, "kind": "subClassOf"})
                    count += walk(c, depth + 1)
            return count

        for r in roots:
            if budget <= 0:
                break
            walk(r, 0)

        # Properties join the canvas after the class tree (spec §7.3). An
        # object property whose domain AND range are both declared, rendered
        # classes becomes ONE labeled class→class edge (kind objectProperty,
        # arrow domain→range) — the property node hub is dropped (user
        # direction 2026-08-31: fewer nodes, relations read at a glance).
        # Everything else falls back to node form: datatype properties (their
        # range is a literal with no node to attach to) and object properties
        # without a usable far end, so they stay visible instead of vanishing.
        prop_nodes: dict[str, dict[str, Any]] = {}
        direct: set[tuple[str, str, str]] = set()
        for e in list(self._ir.entities.values()):
            if budget <= 0:
                break
            if e.type != "Class" or e.eid not in seen:
                continue
            linked: set[str] = set()
            for prop in e.properties:
                if prop.eid in linked:
                    continue
                linked.add(prop.eid)
                if prop.ptype != "DatatypeProperty":
                    # e.referenced_by carries this property's relation to e
                    # plus the far end (counterpart): the range class when e
                    # is the domain, the domain class when e is the range.
                    ref = next((r for r in e.referenced_by if r.eid == prop.eid), None)
                    far = ref.counterpart if ref else None
                    if ref is not None and far and far.declared and far.eid in seen:
                        src, dst = (
                            (e.eid, far.eid) if ref.relation == "rdfs:domain" else (far.eid, e.eid)
                        )
                        if (prop.eid, src, dst) not in direct:
                            direct.add((prop.eid, src, dst))
                            edges.append(
                                {
                                    "source": src,
                                    "target": dst,
                                    "kind": "objectProperty",
                                    "label": prop.curie.split(":")[-1],
                                    "eid": prop.eid,
                                }
                            )
                        continue
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
            **base,
            "nodes": nodes,
            "edges": edges,
            "truncated": depth_cap is not None,
            "total_count": len(self._ir.entities),
        }

    def _progressive_payload(self, include_deprecated: bool) -> dict[str, Any]:
        """Folded root view: one node per root (or prefix bucket), no edges.

        Every node carries folded=True + subtreeSize so the canvas renders
        fold badges; expanding fetches the live children via expand().
        """
        roots = self._roots(include_deprecated)
        nodes: list[dict[str, Any]] = []
        if len(roots) > PREFIX_BUCKET_ROOTS:
            groups: dict[str, list[EntityIR]] = defaultdict(list)
            for r in roots:
                groups[r.curie.split(":", 1)[0] or "(default)"].append(r)
            for prefix, members in sorted(groups.items()):
                nodes.append(
                    {
                        "id": f"__prefix__:{prefix}",
                        "curie": f"{prefix}:*",
                        "label": {},
                        "kind": "prefixBucket",
                        "subtreeSize": len(members),
                        "folded": True,
                    }
                )
        else:
            for r in roots:
                nodes.append(
                    {
                        "id": r.eid,
                        "curie": r.curie,
                        "label": r.label,
                        "kind": "class",
                        "instanceCount": len(self._ir.instances.get(r.eid, [])),
                        "subtreeSize": self.subtree_size(r.eid),
                        "folded": self.subtree_size(r.eid) > 1,
                    }
                )
        dep_count = sum(
            1 for e in list(self._ir.entities.values()) if e.type == "Class" and e.deprecated
        )
        if dep_count:
            nodes.append(
                {
                    "id": DEPRECATED_BUCKET,
                    "curie": DEPRECATED_BUCKET,
                    "label": {},
                    "kind": "deprecatedBucket",
                    "subtreeSize": dep_count,
                    "folded": True,
                }
            )
        return {"nodes": nodes, "edges": []}

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
        for e in sorted(list(self._ir.entities.values()), key=lambda x: x.curie):
            # Class 不是断言属性;AnnotationProperty 只展示不编辑(OWL 2 M1 spec)
            if e.type == "Class" or e.type == "AnnotationProperty":
                continue
            domains = [r for r in e.referenced_by if r.relation == "rdfs:domain"]
            if domains:
                # Prefer a directly-given class over an ancestor hit; both
                # walks are otherwise parse-order dependent (multi-domain).
                hit = next((r for r in domains if r.eid in direct), None) or next(
                    (r for r in domains if r.eid in closure), None
                )
                if hit is None:
                    continue
                inherited = hit.eid not in direct
                via = hit.curie if inherited else None
            else:
                inherited, via = False, None  # domainless: universal
            ranges = [r for r in e.referenced_by if r.relation == "rdfs:range"]
            target = None
            if ranges:
                r0 = sorted(ranges, key=lambda r: r.curie)[0]
                # xsd range: the row lands on a datatype, not a declared class.
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
        """Object assertions whose BOTH ends are in the given set.

        Walks every matching edge so total/truncated stay truthful; the
        payload list is capped at MAX_ASSERTION_EDGES.
        """
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
        total = len(edges)
        return {
            "edges": edges[:MAX_ASSERTION_EDGES],
            "truncated": total > MAX_ASSERTION_EDGES,
            "total": total,
        }


def build_indexes(ir: IRBundle) -> Indexes:
    """Factory kept for API symmetry with build_ir_store."""
    return Indexes(ir)
