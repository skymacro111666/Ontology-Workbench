"""Static site export structure and content."""

from pathlib import Path

import pytest
import rdflib

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.exporter.site import export_site, file_of

MINI = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class ; rdfs:label "A"@en .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:A ; rdfs:range ex:B .
"""

# subClassOf cycle hanging off a root: Root <- A <- B <- A (review finding Q1).
CYCLIC = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:Root a owl:Class .
ex:A a owl:Class ; rdfs:subClassOf ex:Root, ex:B .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
"""

# Label carrying markup: must never reach a rendered page as raw HTML (Q2).
XSS_LABEL = "<img src=x onerror=alert(1)>"
XSS = f"""@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class ; rdfs:label "{XSS_LABEL}"@en .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
"""

# Instances hanging off the classes: drives the entity-page Instances section.
INSTANCED = """@prefix ex: <http://example.org/> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
ex:A a owl:Class ; rdfs:label "A"@en .
ex:B a owl:Class ; rdfs:subClassOf ex:A .
ex:likes a owl:ObjectProperty ; rdfs:domain ex:A ; rdfs:range ex:B .
ex:a1 a ex:A, owl:NamedIndividual ; rdfs:label "first a"@en .
ex:b1 a ex:B, owl:NamedIndividual .
"""


def built_instanced():
    """Parse INSTANCED once into (ir, indexes)."""
    g = rdflib.Graph().parse(data=INSTANCED, format="turtle")
    ir = build_ir(g)
    return ir, build_indexes(ir)


def page_of(tmp_path: Path, eid: str) -> str:
    """Rendered HTML of one entity page, looked up by entity IRI."""
    return (tmp_path / file_of(eid)).read_text(encoding="utf-8")


def built():
    """Parse MINI once into (ir, indexes) for the export tests."""
    g = rdflib.Graph().parse(data=MINI, format="turtle")
    ir = build_ir(g)
    return ir, build_indexes(ir)


def test_export_layout(tmp_path: Path) -> None:
    """Site layout: index page, assets, data files, one page per entity."""
    ir, ix = built()
    result = export_site(ir, ix, tmp_path, title="Mini")
    assert (tmp_path / "index.html").exists()
    assert (tmp_path / "site.js").exists()
    assert (tmp_path / "site.css").exists()
    assert (tmp_path / "data" / "index.json").exists()
    assert (tmp_path / "data" / "entities.json").exists()
    files = sorted((tmp_path / "entities").glob("*.html"))
    assert len(files) == 3  # two classes + one property
    html = files[0].read_text(encoding="utf-8")
    assert "ex:" in html  # CURIE rendered
    assert result.page_count == 4  # index + 3 entities
    assert result.output_dir == tmp_path


def test_search_index_and_entity_map(tmp_path: Path) -> None:
    """data/index.json drives search; data/entities.json maps eid to page file."""
    import json

    ir, ix = built()
    export_site(ir, ix, tmp_path, title="Mini")
    index = json.loads((tmp_path / "data" / "index.json").read_text(encoding="utf-8"))
    assert {e["curie"] for e in index} >= {"ex:A", "ex:B", "ex:likes"}
    assert all({"curie", "label", "eid", "file"} <= set(e) for e in index)
    entities = json.loads((tmp_path / "data" / "entities.json").read_text(encoding="utf-8"))
    assert entities["http://example.org/A"].startswith("entities/")
    # The entity page exists under the mapped filename.
    assert (tmp_path / entities["http://example.org/A"]).exists()


def test_index_page_lists_top_classes_and_stats(tmp_path: Path) -> None:
    """Index page shows title, top-level classes, and counts."""
    ir, ix = built()
    export_site(ir, ix, tmp_path, title="Mini Pizza")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Mini Pizza" in html
    assert "ex:A" in html  # top-level class listed
    assert "2" in html  # class count rendered


def test_refuses_nonempty_out_dir_and_force_overwrites(tmp_path: Path) -> None:
    """Non-empty out dir raises VALIDATION_ERROR; force clears it first."""
    ir, ix = built()
    (tmp_path / "stale.txt").write_text("old", encoding="utf-8")
    with pytest.raises(CoreError) as e:
        export_site(ir, ix, tmp_path, title="Mini")
    assert e.value.code == "VALIDATION_ERROR"
    assert (tmp_path / "stale.txt").exists()  # refused: nothing removed

    export_site(ir, ix, tmp_path, title="Mini", force=True)
    assert not (tmp_path / "stale.txt").exists()
    assert (tmp_path / "index.html").exists()


def test_dark_mode_follows_system(tmp_path: Path) -> None:
    """site.css switches palette via prefers-color-scheme."""
    ir, ix = built()
    export_site(ir, ix, tmp_path, title="Mini")
    css = (tmp_path / "site.css").read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in css


def test_export_survives_subclassof_cycle(tmp_path: Path) -> None:
    """A subClassOf cycle off a root exports fine; both members stay in the tree."""
    g = rdflib.Graph().parse(data=CYCLIC, format="turtle")
    ir = build_ir(g)
    result = export_site(ir, build_indexes(ir), tmp_path, title="Cyclic")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "ex:Root" in html
    assert "ex:A" in html and "ex:B" in html  # cycle members rendered, not crashed
    assert result.page_count == 4  # index + Root + A + B


def test_label_markup_escaped_in_pages_raw_in_data(tmp_path: Path) -> None:
    """Label markup never reaches a rendered page raw; data/index.json stays raw."""
    g = rdflib.Graph().parse(data=XSS, format="turtle")
    ir = build_ir(g)
    export_site(ir, build_indexes(ir), tmp_path, title="XSS")
    pages = list(tmp_path.rglob("*.html"))
    assert pages  # sanity: there are rendered pages to check
    for page in pages:
        assert "<img" not in page.read_text(encoding="utf-8")
    data = (tmp_path / "data" / "index.json").read_text(encoding="utf-8")
    assert XSS_LABEL in data  # data stays raw; only HTML rendering escapes


def test_site_js_uses_dom_apis_not_innerhtml(tmp_path: Path) -> None:
    """Pin the client-side fix: search results are built via DOM APIs, never innerHTML."""
    ir, ix = built()
    export_site(ir, ix, tmp_path, title="Mini")
    js = (tmp_path / "site.js").read_text(encoding="utf-8")
    assert "innerHTML" not in js  # no string-to-markup sink anywhere in the file


def test_class_page_lists_instances(tmp_path: Path) -> None:
    """A class page carries an Instances section with its named individuals."""
    ir, ix = built_instanced()
    export_site(ir, ix, tmp_path, title="Inst")
    a_page = page_of(tmp_path, "http://example.org/A")
    assert "Instances" in a_page
    assert "ex:a1" in a_page
    b_page = page_of(tmp_path, "http://example.org/B")
    assert "ex:b1" in b_page


def test_label_heads_the_entity_page(tmp_path: Path) -> None:
    """h1 shows the human label first; the CURIE demotes to a subtitle line.

    A reader's first sight must be "A", not the machine code ex:A. B has no
    label, so its page falls back to the CURIE as the heading.
    """
    ir, ix = built_instanced()
    export_site(ir, ix, tmp_path, title="Inst")
    a_page = page_of(tmp_path, "http://example.org/A")
    assert "<h1>A " in a_page  # label + type pill; curie no longer the heading
    assert '<p class="curie-line">' in a_page and "<code>ex:A</code>" in a_page
    b_page = page_of(tmp_path, "http://example.org/B")
    assert "<h1>ex:B " in b_page  # no label → CURIE takes the heading


def test_search_index_carries_type_and_js_renders_badge(tmp_path: Path) -> None:
    """index.json entries expose type; site.js renders it as a result badge."""
    import json

    ir, ix = built_instanced()
    export_site(ir, ix, tmp_path, title="Inst")
    index = json.loads((tmp_path / "data" / "index.json").read_text(encoding="utf-8"))
    types = {e["type"] for e in index}
    assert types >= {"Class", "ObjectProperty"}
    js = (tmp_path / "site.js").read_text(encoding="utf-8")
    assert "entry.type" in js


def test_sidebar_lists_properties(tmp_path: Path) -> None:
    """Sidebar gains a (collapsed) Properties group alongside the class tree."""
    ir, ix = built_instanced()
    export_site(ir, ix, tmp_path, title="Inst")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "<summary>Properties</summary>" in html
    assert "ex:likes" in html  # the property is navigable from every page


def test_class_page_shows_ancestor_breadcrumbs(tmp_path: Path) -> None:
    """B's page leads with a crumb trail Root-ward; top-level A has none."""
    ir, ix = built_instanced()
    export_site(ir, ix, tmp_path, title="Inst")
    b_page = page_of(tmp_path, "http://example.org/B")
    assert 'class="crumbs"' in b_page
    assert "ex:A" in b_page  # the parent appears inside the trail
    a_page = page_of(tmp_path, "http://example.org/A")
    assert 'class="crumbs"' not in a_page  # root class: no trail


def test_breadcrumbs_survive_subclassof_cycle(tmp_path: Path) -> None:
    """Crumb computation must not loop on a subClassOf cycle."""
    g = rdflib.Graph().parse(data=CYCLIC, format="turtle")
    ir = build_ir(g)
    export_site(ir, build_indexes(ir), tmp_path, title="Cyclic")
    a_page = page_of(tmp_path, "http://example.org/A")
    assert 'class="crumbs"' in a_page  # terminates and still renders a trail


def test_site_css_carries_brand_palette_and_system_fonts(tmp_path: Path) -> None:
    """The IT-business restyle palette and type.

    Brand indigo accent, slate neutrals, and a system font stack (no CDN
    dependency — the site may open over file://).
    """
    ir, ix = built()
    export_site(ir, ix, tmp_path, title="Mini")
    css = (tmp_path / "site.css").read_text(encoding="utf-8")
    assert "#4f46e5" in css  # brand indigo accent
    assert "system-ui" in css  # system font stack, not webfonts
    assert "prefers-color-scheme: dark" in css  # dark theme still follows system


def test_entity_page_uses_section_cards_and_typed_badges(tmp_path: Path) -> None:
    """Sections render as cards; entity type and labels ride typed badges."""
    ir, ix = built_instanced()
    export_site(ir, ix, tmp_path, title="Inst")
    a_page = page_of(tmp_path, "http://example.org/A")
    assert 'class="card"' in a_page  # section cards
    assert "tag--class" in a_page  # typed badge for the Class pill
    assert "tag--label" in a_page  # labels ride the label badge


def test_search_badges_and_sidebar_highlight_use_typed_classes(tmp_path: Path) -> None:
    """Typed classes for search badges and sidebar highlight.

    site.js badge classes are typed; the sidebar current-page highlight is
    a CSS class (not an inline style).
    """
    ir, ix = built()
    export_site(ir, ix, tmp_path, title="Mini")
    js = (tmp_path / "site.js").read_text(encoding="utf-8")
    assert "tag--" in js  # typed badge for search results
    assert "style.fontWeight" not in js  # highlight via class, not inline style
