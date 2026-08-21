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
