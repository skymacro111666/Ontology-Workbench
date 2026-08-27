<div align="center">

# Ontology Workbench

**A self-hosted, open-source ontology workbench — explore, edit, and publish ontologies**

[![CI](../../../actions/workflows/ci.yml/badge.svg)](../../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](../../../LICENSE)
[![English](https://img.shields.io/badge/English-README-blue)](README.en.md)
[![简体中文](https://img.shields.io/badge/简体中文-README-gray)](../../README.md)

[Features](#-features) · [Get Started](#-get-started) · [License](#-license)

</div>

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

## 📄 License

[Apache License 2.0](../../LICENSE) · Copyright 2026 The Ontology Workbench Authors.
