"""Static docs-site export: renders the IR into a deployable HTML tree.

One page per entity plus an index page, a client-side search index, and a
small native-JS layer (spec §8). The exporter consumes the same IR the API
serves - the double consumer is the point of the IR abstraction.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from uuid import UUID

from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from ontoworkbench.core.errors import CoreError
from ontoworkbench.core.indexes import Indexes
from ontoworkbench.core.ir import EntityIR, IRBundle

_TEMPLATES = Path(__file__).parent / "templates"


class ExportResult(BaseModel):
    """Outcome of one export run."""

    output_dir: Path
    page_count: int


def default_out_dir(data_dir: Path, ontology_id: UUID) -> Path:
    """Timestamped default target shared by the API route and the CLI."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return data_dir / "exports" / f"{ontology_id}-{stamp}"


def file_of(eid: str) -> str:
    """Stable page filename for an entity IRI (sha1 prefix, HTML-safe)."""
    return f"entities/{hashlib.sha1(eid.encode()).hexdigest()[:16]}.html"


def _env() -> Environment:
    loader = FileSystemLoader(str(_TEMPLATES))
    return Environment(loader=loader, autoescape=True)


def _sidebar_tree(indexes: Indexes) -> list[dict]:
    """Nested class tree for the sidebar: curie/eid/file/children."""

    def leaf_of(child: EntityIR) -> dict:
        return {"curie": child.curie, "eid": child.eid, "file": file_of(child.eid), "children": []}

    def node_of(e: EntityIR, seen: frozenset[str]) -> dict:
        # seen is the root-to-e eid path; a child already on it closes a
        # subClassOf cycle - render it as a leaf instead of descending
        # (same posture as core's _total_descendants cycle guard).
        path = seen | {e.eid}
        return {
            "curie": e.curie,
            "eid": e.eid,
            "file": file_of(e.eid),
            "children": [
                node_of(child, path) if child.eid not in path else leaf_of(child)
                for c in e.children
                if (child := indexes.entity(c.eid)) is not None
            ]
            if e.type == "Class"
            else [],
        }

    roots: list[dict] = []
    for tn in indexes.tree(None):
        ent = indexes.entity(tn.eid)
        if ent is not None:
            roots.append(node_of(ent, frozenset()))
    return roots


def _sidebar_props(ir: IRBundle) -> dict[str, list[dict]]:
    """Sidebar property groups (object above data): curie/file per entry.

    Only explicitly typed properties ever become entities, so two groups
    cover everything - there is no third bucket to fill.
    """
    groups: dict[str, list[dict]] = {"object": [], "data": []}
    for e in ir.entities.values():
        if e.type == "ObjectProperty":
            groups["object"].append({"curie": e.curie, "file": file_of(e.eid)})
        elif e.type == "DatatypeProperty":
            groups["data"].append({"curie": e.curie, "file": file_of(e.eid)})
    return groups


def _crumbs(indexes: Indexes, e: EntityIR) -> list[dict]:
    """First-parent ancestor chain, root first.

    A subClassOf cycle cuts at the first revisit
    (same posture as _sidebar_tree's guard).
    """
    chain: list[dict] = []
    seen = {e.eid}
    cur = e
    while cur.parents:
        head = cur.parents[0]
        if head.eid in seen:
            break
        ent = indexes.entity(head.eid)
        if ent is None:
            break
        chain.append({"curie": head.curie, "file": file_of(head.eid)})
        seen.add(head.eid)
        cur = ent
    chain.reverse()
    return chain


def export_site(
    ir: IRBundle,
    indexes: Indexes,
    out_dir: Path,
    title: str,
    force: bool = False,
) -> ExportResult:
    """Render the whole site under out_dir; refuse non-empty dirs unless force."""
    if out_dir.exists() and any(out_dir.iterdir()):
        if not force:
            raise CoreError(
                "VALIDATION_ERROR",
                f"Output directory not empty: {out_dir}",
                "Choose another --out or pass force=true",
            )
        for child in out_dir.iterdir():
            shutil.rmtree(child) if child.is_dir() else child.unlink()

    (out_dir / "entities").mkdir(parents=True, exist_ok=True)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)
    env = _env()
    tree = _sidebar_tree(indexes)
    props = _sidebar_props(ir)
    tab_counts = {
        "classes": ir.counts.class_count,
        "properties": len(props["object"]) + len(props["data"]),
    }
    # Footer provenance shared by every page (base.html.j2).
    footer = {
        "exported_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "ontology_iri": ir.ontology_iri,
    }

    entity_tpl = env.get_template("entity.html.j2")
    search_index: list[dict] = []
    entity_map: dict[str, str] = {}
    for e in ir.entities.values():
        rel = file_of(e.eid)
        entity_map[e.eid] = rel
        search_index.append(
            {"curie": e.curie, "label": e.label, "eid": e.eid, "file": rel, "type": e.type}
        )
        page = entity_tpl.render(
            title=f"{e.curie} - {title}",
            site_title=title,
            e=e,
            file_of=file_of,
            tree=tree,
            props=props,
            instances=ir.instances.get(e.eid, []),
            crumbs=_crumbs(indexes, e),
            known_eids=set(ir.entities),
            root="../",  # entity pages sit one level below the site root
            tab_counts=tab_counts,
            **footer,
        )
        (out_dir / rel).write_text(page, encoding="utf-8")

    index_page = env.get_template("index.html.j2").render(
        title=title,
        site_title=title,
        counts=ir.counts,
        prefixes=ir.prefixes,
        tree=tree,
        props=props,
        top_classes=tree,
        root="",  # index.html sits at the site root
        tab_counts=tab_counts,
        **footer,
    )
    (out_dir / "index.html").write_text(index_page, encoding="utf-8")

    (out_dir / "data" / "index.json").write_text(
        json.dumps(search_index, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # The same index as a script-tag global: fetch() cannot read local files
    # (file://), but <script src> loads anywhere. "</" is escaped so an
    # embedded ontology string can never close the element early.
    index_payload = json.dumps(search_index, ensure_ascii=False).replace("</", "<\\/")
    (out_dir / "data" / "search-index.js").write_text(
        f"window.__OW_INDEX__ = {index_payload};\n", encoding="utf-8"
    )
    (out_dir / "data" / "entities.json").write_text(
        json.dumps(entity_map, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    for asset in ("site.css", "site.js", "favicon.svg"):
        shutil.copyfile(_TEMPLATES / asset, out_dir / asset)

    return ExportResult(output_dir=out_dir, page_count=1 + len(entity_map))
