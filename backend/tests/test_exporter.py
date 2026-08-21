"""Static site export structure and content."""

from pathlib import Path

import pytest
import rdflib

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.indexes import build_indexes
from ontoworkbench.core.ir import build_ir
from ontoworkbench.exporter.site import export_site

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
