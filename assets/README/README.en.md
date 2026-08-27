<div align="center">

# Ontology Workbench

**Everything you need to explore, edit and publish ontologies — self-hosted, data local.**

[![CI](../../../actions/workflows/ci.yml/badge.svg)](../../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](../../../LICENSE)
[![English](https://img.shields.io/badge/English-current-blue)](README.en.md)
[![简体中文](https://img.shields.io/badge/简体中文-README-gray)](../../README.md)

[Features](#-features) · [Get Started](#-get-started) · [Tour](#-tour) · [License](#-license)

</div>

A self-hosted, open-source workbench for OWL ontologies — an "IDE for ontologies" running on your own server. Upload an ontology, browse it through a class tree with instant search, visualize it on a graph canvas, **edit it** (on the canvas or in the Turtle source), and export a deployable static docs site in one click. Your data never leaves your server.

## ✨ Features

- **Three-pane reading workspace** — class/property/prefix sidebar, instant search, breadcrumb lineage; virtualized tree keeps large ontologies smooth
- **Three view modes per entity** — detail / split / graph, plus a back-reference panel answering "who references me"
- **Graph visualization** — G6 canvas for local-neighbor and global-overview graphs, semantically colored edges, drag positions persisted server-side
- **Canvas editing** — right-click to create/edit/delete classes and properties; back-references pruned with them; optimistic locking prevents conflicts
- **Source editing** — CodeMirror-powered Turtle editor with find/replace, dirty-state guards, and parse-before-save
- **One-click docs export** — a zero-dependency static site, ready for GitHub Pages
- **Engineering core** — JSON structured logs, Prometheus metrics, and a scriptable `ow` CLI for CI

## 🚀 Get Started

### Option 1: Docker (recommended)

```bash
git clone https://github.com/skymacro111666/ontology-workbench.git
cd ontology-workbench
docker compose up -d --build
```

Open `http://127.0.0.1:8734`. Data lives in the project-local `./data` and `./logs` directories and survives container rebuilds; `OW_PORT=9000 docker compose up -d` changes the port, and if `OW_JWT_SECRET` is unset a secret is generated once and kept in `data/jwt-secret`.

### Option 2: From source

Prerequisites: Python ≥ 3.11 with [uv](https://docs.astral.sh/uv/); Node.js ≥ 22 with npm.

```bash
git clone https://github.com/skymacro111666/ontology-workbench.git
cd ontology-workbench

# 1) backend deps
cd backend && uv sync

# 2) frontend build (the SPA is served by the backend on the same port)
cd ../frontend && npm ci && npm run build

# 3) start (auto-opens the browser on a loopback TTY; --no-browser disables)
cd ../backend && uv run ow serve
```

The first visit walks you through a one-time admin setup; log in and load a bundled sample ontology. **Config precedence: CLI flags > environment variables (`.env`) > defaults**; common variables are `OW_HOST` / `OW_PORT` / `OW_DATA_DIR` / `OW_DB_URL` (SQLite by default, PostgreSQL supported) / `OW_LOG_LEVEL`.

## 🧭 Tour

### 🗂 Workspace: three panes

<!-- screenshot placeholder: assets/README/screenshots/browse-tree.png -->

- **Top bar**: ontology title, instant search (150ms debounce, case-insensitive substring across labels / local names / comments), overview entry, export button
- **Sidebar**: stats header ("101 classes · 38 properties") and three tabs — **Classes** (`rdfs:subClassOf` tree, virtualized + lazy-loaded), **Properties** (object / datatype), **Prefixes** (prefix ↔ IRI table)
- **Content**: breadcrumb lineage (`schema:Thing › Person`); status bar shows filename, class/property counts, triples and parse time

### 🔍 Entity detail: three views

<!-- screenshot placeholder: assets/README/screenshots/browse-backrefs.png -->

1. **Detail** — multilingual labels, comments, parents/children, the back-reference panel ("who references me", index-driven) and **raw TTL** (complex axioms shown as original Turtle fragments)
2. **Split** — local-neighbor graph beside the detail pane
3. **Graph** — the neighbor graph full-width

<!-- screenshot placeholder: assets/README/screenshots/browse-split.png -->

### 🕸 Graph visualization

<!-- screenshot placeholder: assets/README/screenshots/graph-overview.png -->

One G6 canvas, two data sources: the per-entity **local-neighbor graph** and the **global overview** (click a node to open its detail). Edges are semantically colored: `subClassOf` purple dashed, object properties cyan solid, datatype properties gray dotted; node badges count direct subclasses. **Large ontologies degrade gracefully**: over 500 overview nodes collapse to the top 3 levels. **Persisted layouts**: dragged positions are saved server-side and restored on reopen; a reset button returns to auto-layout.

### ✏️ Canvas editing

<!-- screenshot placeholder: assets/README/screenshots/graph-context-menu.png -->

Right-click on the canvas: blank space creates a class; a class node offers subclass / object property / datatype property creation (domain pre-filled), edit, and delete. Dialogs pick prefix, parents, and range (a class for object properties, an XSD type for datatype properties); delete defaults to **prune** — subclass assertions, property domains/ranges and instance types referencing the entity are cleaned up too. Every write carries a **baseFileHash optimistic lock**; if the file changed elsewhere the write is rejected with a refresh hint.

<!-- screenshot placeholder: assets/README/screenshots/entity-dialog.png -->

### 📝 Source editing

<!-- screenshot placeholder: assets/README/screenshots/source-edit.png -->

The text view is an editor: CodeMirror syntax highlighting, find/replace (Ctrl+F or the toolbar button), dirty marker and a switch guard (save / discard / cancel). Saves are **parse-gated** — a syntax error rejects the write and leaves the file untouched — and share the same optimistic-lock pipeline as canvas edits.

### 📤 Docs-site export

<!-- screenshot placeholder: assets/README/screenshots/export.png -->

The `/export` page, `POST /api/ontologies/{id}/export/site` and `ow export-site <id>` share one export path producing a **zero-dependency** static site:

```
{out}/
├── index.html            # overview: stats, prefixes, top-class entries
├── entities/{hash}.html  # one page per entity
├── data/index.json       # static search index
└── site.css / site.js    # vanilla JS: tree nav + client-side search
```

Deploy the output to GitHub Pages or any static server; a non-empty target is refused (use `--out` elsewhere or explicit `--force`).

### 📥 Upload & samples

<!-- screenshot placeholder: assets/README/screenshots/home.png -->

Drag-and-drop Turtle (`.ttl`), RDF-XML (`.owl` / `.rdf`) or JSON-LD (`.jsonld`), up to 150MB per file, format sniffed by extension and content; **Pizza / Wine / FOAF** samples load with one click.

## 📄 License

[Apache License 2.0](../../LICENSE) · Copyright 2026 The Ontology Workbench Authors.
