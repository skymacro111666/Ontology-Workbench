"""Tree/search/neighbors/overview from IR."""

import rdflib

from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir

MINI = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:comment "loyal"@en .
"""


def make():
    """Build indexes over the MINI ontology."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    return build_indexes(build_ir(g))


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


def test_overview_truncates_large_graphs() -> None:
    """Above max_nodes the overview degrades to top levels and flags it."""
    import io

    buf = io.StringIO()
    buf.write(
        "@prefix ex: <http://example.org/> .\n@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
    )
    buf.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
    buf.write("ex:Root a owl:Class .\n")
    for i in range(600):
        buf.write(f"ex:C{i} a owl:Class ; rdfs:subClassOf ex:Root .\n")
    g = rdflib.Graph().parse(data=buf.getvalue(), format="turtle")
    ix = build_indexes(build_ir(g))
    ov = ix.overview()
    assert ov["truncated"] is True
    assert ov["total_count"] == 601
    assert len(ov["nodes"]) < ov["total_count"]


MINI_DIAMOND = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class .
ex:B a owl:Class .
ex:Child a owl:Class ; rdfs:subClassOf ex:A , ex:B .
"""


def test_overview_multi_parent_child_not_duplicated() -> None:
    """A child reachable from several roots/branches appears once.

    G6 (canvas) keys nodes by id — duplicate ids crash the whole page
    (wine#Sauternes / foaf:Person blanks), so the walk must dedupe nodes
    while still emitting one edge per real parent link.
    """
    g = rdflib.Graph().parse(data=MINI_DIAMOND, format="turtle")
    ix = build_indexes(build_ir(g))
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
ex:Thing a owl:Class .
ex:Animal a owl:Class ; rdfs:subClassOf ex:Thing ; rdfs:comment "alive"@en .
ex:Dog a owl:Class ; rdfs:subClassOf ex:Animal ; rdfs:label "小狗狗"@en .
ex:Cat a owl:Class ; rdfs:subClassOf ex:Animal .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:Dog ; rdfs:range ex:Cat .
ex:Ghost a owl:Class ; rdfs:subClassOf <http://external.org/X> .
"""


def make2():
    """Build indexes over MINI2 (labels, siblings, properties, orphan)."""
    g = rdflib.Graph().parse(data=MINI2, format="turtle")
    return build_indexes(build_ir(g))


def test_orphan_class_with_external_parent_is_root() -> None:
    """A class whose only parent is undeclared still renders as a root."""
    ix = make2()
    roots = {r.curie for r in ix.tree(None)}
    assert "ex:Ghost" in roots
    assert "ex:Thing" in roots
    ov = ix.overview()
    ghost_nodes = [n for n in ov["nodes"] if n["curie"] == "ex:Ghost"]
    assert ghost_nodes, "orphan class must appear in the overview"
    assert ov["total_count"] == 6


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
