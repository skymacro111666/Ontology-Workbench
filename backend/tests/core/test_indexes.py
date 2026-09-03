"""Tree/search/neighbors/overview from IR."""

from ontoworkbench.core.indexes import Indexes, build_indexes
from ontoworkbench.core.ir import build_ir_store
from ontoworkbench.core.parsing import parse_store


def _ir(ttl: str):
    """Build the IR bundle over ttl text."""
    return build_ir_store(*parse_store(ttl.encode(), "turtle"))


MINI = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:comment "loyal"@en .
"""


def make():
    """Build indexes over the MINI ontology."""
    return build_indexes(_ir(MINI))


def test_tree_roots_and_children() -> None:
    """Roots come back for parent=None; children for a parent eid."""
    ix = make()
    roots = ix.tree(None)
    assert [r.curie for r in roots] == ["ex:Thing"]
    assert roots[0].children_count == 1
    kids = ix.tree("http://example.org/Animal")
    assert [k.curie for k in kids] == ["ex:Dog"]
    assert kids[0].children_count == 0


def test_search_label_comment_localname() -> None:
    """Search matches localname, label, and comment case-insensitively."""
    ix = make()
    hits = ix.search("dog")
    assert hits[0].curie == "ex:Dog"
    assert hits[0].matched_field == "localname"
    assert ix.search("loyal")[0].matched_field == "comment"
    assert ix.search("zzz") == []


def test_neighbors_local_view() -> None:
    """Neighbors include parents, children, siblings, and properties."""
    ix = make()
    nb = ix.neighbors("http://example.org/Animal")
    curies = {n["curie"] for n in nb["nodes"]}
    assert curies == {"ex:Animal", "ex:Thing", "ex:Dog"}
    assert any(e["kind"] == "subClassOf" for e in nb["edges"])


def test_overview_small_graph_not_truncated() -> None:
    """A small graph is fully rendered and not flagged truncated."""
    ix = make()
    ov = ix.overview()
    assert ov["truncated"] is False
    assert ov["total_count"] == 3
    assert len(ov["nodes"]) == 3 and len(ov["edges"]) == 2


def _chain(n: int) -> str:
    """A linear class hierarchy L0 <- L1 <- ... <- L(n-1), as Turtle text."""
    ttl = (
        "@prefix ex: <http://example.org/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "ex:L0 a owl:Class .\n"
    )
    ttl += "".join(f"ex:L{i} a owl:Class ; rdfs:subClassOf ex:L{i - 1} .\n" for i in range(1, n))
    return ttl


def test_overview_renders_full_depth_within_budget() -> None:
    """Within the node budget the hierarchy renders at full depth (spec §7.5)."""
    ix = build_indexes(_ir(_chain(6)))
    ov = ix.overview()
    assert ov["truncated"] is False
    assert len(ov["nodes"]) == 6
    assert sum(1 for e in ov["edges"] if e["kind"] == "subClassOf") == 5


def test_overview_degrades_to_three_levels_past_budget() -> None:
    """Past the node budget only the top 3 levels render, flagged truncated."""
    ix = build_indexes(_ir(_chain(20)))
    ov = ix.overview(max_nodes=5)
    assert ov["truncated"] is True
    assert len(ov["nodes"]) == 4  # levels 0-3 of the chain
    assert len(ov["edges"]) == 3


def test_overview_truncates_large_graphs() -> None:
    """Above max_nodes the overview degrades to top levels and flags it."""
    ttl = (
        "@prefix ex: <http://example.org/> .\n@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
        "ex:Root a owl:Class .\n"
    )
    ttl += "".join(f"ex:C{i} a owl:Class ; rdfs:subClassOf ex:Root .\n" for i in range(600))
    ix = build_indexes(_ir(ttl))
    ov = ix.overview(max_nodes=100)
    assert ov["truncated"] is True
    assert ov["total_count"] == 601
    assert len(ov["nodes"]) == 100


def test_overview_budget_default_is_5000() -> None:
    """The default canvas budget is 5000 (user decision, 2026-08-24)."""
    from ontoworkbench.core.indexes import MAX_OVERVIEW_NODES

    assert MAX_OVERVIEW_NODES == 5000


def test_overview_includes_property_nodes_and_typed_edges() -> None:
    """Spec §7.3, revised 2026-08-31: object properties become edges.

    Declared domain+range renders as ONE direct class→class edge
    (objectProperty) instead of a hub node; datatype properties keep node
    form with dotted 'datatype' edges (their range is a literal).
    """
    ix = make2()
    ov = ix.overview()
    curies = {n["curie"] for n in ov["nodes"]}
    assert "ex:likes" not in curies  # direct edge, not a node
    assert "ex:age" in curies
    ptypes = {n["curie"]: n.get("ptype") for n in ov["nodes"]}
    assert ptypes["ex:age"] == "DatatypeProperty"
    # Class nodes stay ptype-free; the field only distinguishes properties.
    assert ptypes["ex:Dog"] is None
    triples = {(e["source"], e["target"], e["kind"]) for e in ov["edges"]}
    dog = "http://example.org/Dog"
    cat = "http://example.org/Cat"
    assert (dog, cat, "objectProperty") in triples
    assert (dog, "http://example.org/age", "datatype") in triples
    # External range (xsd:integer) is not an entity and must not dangle.
    assert all(e["target"] in {n["id"] for n in ov["nodes"]} for e in ov["edges"])


MINI_DIAMOND = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class .
ex:B a owl:Class .
ex:Child a owl:Class ; rdfs:subClassOf ex:A , ex:B .
"""


MINI3 = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Animal a owl:Class .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal .
ex:Cat a owl:Class ; rdfs:subClassOf ex:Animal .
ex:rex a owl:NamedIndividual , ex:Dog ; rdfs:label "Rex"@en .
ex:buddy a owl:NamedIndividual , ex:Dog .
ex:whiskers a owl:NamedIndividual , ex:Cat .
"""


def make3():
    """Build indexes over MINI3 (classes with named individuals)."""
    return build_indexes(_ir(MINI3))


def test_tree_reports_instance_counts() -> None:
    """Tree nodes carry each class's direct-instance count (sidebar badge)."""
    ix = make3()
    roots = {r.curie: r.instance_count for r in ix.tree(None)}
    assert roots["ex:Animal"] == 0
    kids = {k.curie: k.instance_count for k in ix.tree("http://example.org/Animal")}
    assert kids["ex:Dog"] == 2
    assert kids["ex:Cat"] == 1


def test_overview_reports_instance_counts() -> None:
    """Overview nodes carry the class's direct-instance count (badge data)."""
    ix = make3()
    ov = ix.overview()
    counts = {n["curie"]: n.get("instance_count") for n in ov["nodes"]}
    assert counts["ex:Dog"] == 2
    assert counts["ex:Cat"] == 1
    assert counts["ex:Animal"] == 0
    # Instances stay off the schema canvas until asked for.
    assert all(n["kind"] == "class" for n in ov["nodes"])


def test_instances_payload_is_canvas_shaped() -> None:
    """instances(eid) returns canvas-ready nodes/edges, instance kind."""
    ix = make3()
    payload = ix.instances("http://example.org/Dog")
    assert [n["curie"] for n in payload["nodes"]] == ["ex:buddy", "ex:rex"]
    assert all(n["kind"] == "instance" for n in payload["nodes"])
    assert payload["edges"] == [
        {
            "source": "http://example.org/buddy",
            "target": "http://example.org/Dog",
            "kind": "instance",
        },
        {
            "source": "http://example.org/rex",
            "target": "http://example.org/Dog",
            "kind": "instance",
        },
    ]
    # A class without instances yields an empty canvas payload, not an error.
    assert ix.instances("http://example.org/Animal") == {"nodes": [], "edges": []}


def test_overview_multi_parent_child_not_duplicated() -> None:
    """A child reachable from several roots/branches appears once.

    G6 (canvas) keys nodes by id — duplicate ids crash the whole page
    (wine#Sauternes / foaf:Person blanks), so the walk must dedupe nodes
    while still emitting one edge per real parent link.
    """
    ix = build_indexes(_ir(MINI_DIAMOND))
    ov = ix.overview()
    ids = [n["id"] for n in ov["nodes"]]
    assert len(ids) == len(set(ids)) == 3
    pairs = {(e["source"], e["target"]) for e in ov["edges"]}
    assert pairs == {
        ("http://example.org/Child", "http://example.org/A"),
        ("http://example.org/Child", "http://example.org/B"),
    }


MINI2 = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing ; rdfs:comment "alive"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "小狗狗"@en .
ex:Cat a owl:Class ; rdfs:subClassOf ex:Animal .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:Dog ; rdfs:range ex:Cat .
ex:age a owl:DatatypeProperty ; rdfs:domain ex:Dog ; rdfs:range xsd:integer .
ex:Ghost a owl:Class ; rdfs:subClassOf <http://external.org/X> .
"""


def make2():
    """Build indexes over MINI2 (labels, siblings, properties, orphan)."""
    return build_indexes(_ir(MINI2))


def test_orphan_class_with_external_parent_is_root() -> None:
    """A class whose only parent is undeclared still renders as a root."""
    ix = make2()
    roots = {r.curie for r in ix.tree(None)}
    assert "ex:Ghost" in roots
    assert "ex:Thing" in roots
    ov = ix.overview()
    ghost_nodes = [n for n in ov["nodes"] if n["curie"] == "ex:Ghost"]
    assert ghost_nodes, "orphan class must appear in the overview"
    assert ov["total_count"] == 7


def test_neighbors_cover_siblings_and_properties() -> None:
    """Dog's local view includes its sibling Cat and property likes."""
    ix = make2()
    nb = ix.neighbors("http://example.org/Dog")
    curies = {n["curie"] for n in nb["nodes"]}
    assert "ex:Cat" in curies
    assert "ex:likes" in curies
    kinds = {(e["source"], e["target"]) for e in nb["edges"] if e["kind"] == "property"}
    assert ("http://example.org/Dog", "http://example.org/likes") in kinds


def test_search_hits_label_branch() -> None:
    """A query matching only the label (not localname/comment) returns a hit."""
    ix = make2()
    hits = ix.search("小狗狗")
    assert [h.curie for h in hits] == ["ex:Dog"]
    assert hits[0].matched_field == "label"


def test_individual_lookup_and_instance_search() -> None:
    """individual() 命中;search 覆盖实例并支持 type 过滤。."""
    from pathlib import Path

    data = (Path(__file__).parents[2] / "ontoworkbench" / "samples" / "library.ttl").read_bytes()
    ix = build_indexes(build_ir_store(*parse_store(data, "turtle")))

    tb_eid = "https://github.com/skymacro111666/ontology-workbench/samples/library#ThreeBody"
    assert ix.individual(tb_eid) is not None and ix.individual(tb_eid).kind == "instance"
    assert (
        ix.individual("https://github.com/skymacro111666/ontology-workbench/samples/library#Nope")
        is None
    )
    assert ix.ir.counts.individual_count > 0  # ir 暴露

    hits = ix.search("three", 20)
    assert any(h.type == "Instance" and h.eid == tb_eid for h in hits)
    only_inst = ix.search("three", 20, type_="Instance")
    assert only_inst and all(h.type == "Instance" for h in only_inst)
    only_cls = ix.search("three", 20, type_="Class")
    assert all(h.type != "Instance" for h in only_cls)


ASSERT_MINI = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
ex:Parent a owl:Class .
ex:Child a owl:Class ; rdfs:subClassOf ex:Parent .
ex:directProp a owl:ObjectProperty ; rdfs:domain ex:Child ; rdfs:range ex:Parent .
ex:parentProp a owl:DatatypeProperty ; rdfs:domain ex:Parent ; rdfs:range xsd:integer .
ex:freeProp a owl:ObjectProperty .
ex:multiProp a owl:ObjectProperty ; rdfs:domain ex:Parent , ex:Child ; rdfs:range ex:Parent .
"""


def test_assertion_schema_branches() -> None:
    """Direct / inherited / domainless / multi-domain props with their targets."""
    ix = build_indexes(_ir(ASSERT_MINI))
    props = {p.curie: p for p in ix.assertion_schema(["http://example.org/Child"])}
    assert set(props) == {"ex:directProp", "ex:parentProp", "ex:freeProp", "ex:multiProp"}

    direct = props["ex:directProp"]
    assert direct.inherited is False and direct.via is None
    assert direct.target is not None
    assert direct.target.kind == "class"
    assert direct.target.curie == "ex:Parent" and direct.target.declared is True

    inherited = props["ex:parentProp"]
    assert inherited.inherited is True and inherited.via == "ex:Parent"
    assert inherited.target is not None
    assert inherited.target.kind == "datatype" and inherited.target.declared is None

    free = props["ex:freeProp"]
    assert free.inherited is False and free.via is None and free.target is None

    # A direct domain hit wins over an ancestor hit regardless of row order.
    multi = props["ex:multiProp"]
    assert multi.inherited is False and multi.via is None


def _linked(n: int, cap: int | None = None) -> tuple[Indexes, list[str], int]:
    """Build n individuals with ex:knows between every ordered pair (i != j).

    cap stops emitting pairs early; returns indexes, eids, and the true
    edge count — the fixture for truthful truncation totals.
    """
    ttl = (
        "@prefix ex: <http://example.org/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "ex:knows a owl:ObjectProperty .\n"
    )
    ttl += "".join(f"ex:w{i} a owl:NamedIndividual .\n" for i in range(n))
    count = 0
    for i in range(n):
        for j in range(n):
            if i == j or (cap is not None and count >= cap):
                continue
            ttl += f"ex:w{i} ex:knows ex:w{j} .\n"
            count += 1
    ix = build_indexes(_ir(ttl))
    return ix, [f"http://example.org/w{i}" for i in range(n)], count


def test_assertion_edges_over_cap_totals_truthful() -> None:
    """Past the cap: 500 returned, truncated flagged, total is the TRUE count."""
    ix, eids, true_total = _linked(23)  # 23 * 22 = 506 matching pairs
    out = ix.assertion_edges(eids)
    assert len(out["edges"]) == 500
    assert out["truncated"] is True
    assert out["total"] == true_total == 506


def test_assertion_edges_exactly_at_cap_not_truncated() -> None:
    """Exactly 500 matching edges: nothing is dropped, truncated stays False."""
    ix, eids, true_total = _linked(23, cap=500)
    out = ix.assertion_edges(eids)
    assert out["truncated"] is False
    assert out["total"] == len(out["edges"]) == 500 == true_total


def test_assertion_edges_sub_cap_full_payload() -> None:
    """Under the cap every matching edge returns with honest totals."""
    ix, eids, _ = _linked(5)  # 5 * 4 = 20 pairs
    out = ix.assertion_edges(eids)
    assert out["truncated"] is False
    assert out["total"] == len(out["edges"]) == 20
    assert {e["label"] for e in out["edges"]} == {"knows"}


HR = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Employee a owl:Class .
ex:Department a owl:Class .
ex:worksIn a owl:ObjectProperty ; rdfs:domain ex:Employee ; rdfs:range ex:Department .
ex:badgeNo a owl:DatatypeProperty ; rdfs:domain ex:Employee .
"""


def make_hr():
    """Indexes over a domain/range object property plus a datatype one."""
    return build_indexes(_ir(HR))


def test_overview_object_property_becomes_direct_edge() -> None:
    """Domain+range declared → one labeled class→class edge, no prop node."""
    ix = make_hr()
    ov = ix.overview()
    assert not any(n["curie"] == "ex:worksIn" for n in ov["nodes"])
    direct = [e for e in ov["edges"] if e["kind"] == "objectProperty"]
    assert len(direct) == 1
    assert direct[0]["source"] == "http://example.org/Employee"
    assert direct[0]["target"] == "http://example.org/Department"
    assert direct[0]["label"] == "worksIn"
    assert direct[0]["eid"] == "http://example.org/worksIn"
    # Datatype properties keep the node form (their range is a literal).
    assert any(n["curie"] == "ex:badgeNo" for n in ov["nodes"])
    assert any(e["kind"] == "datatype" for e in ov["edges"])


def test_overview_object_property_without_range_keeps_node() -> None:
    """No usable far end → the property falls back to node form.

    It stays visible rather than vanishing from the canvas.
    """
    ttl = HR.replace(" ; rdfs:range ex:Department .", " .", 1)
    ix = build_indexes(_ir(ttl))
    ov = ix.overview()
    assert any(n["curie"] == "ex:worksIn" for n in ov["nodes"])
    assert any(e["kind"] == "property" for e in ov["edges"])
    assert not any(e["kind"] == "objectProperty" for e in ov["edges"])
