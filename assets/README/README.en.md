<div align="center">

# Ontology Workbench

**A self-hosted, open-source ontology workbench — explore, edit, and publish ontologies**

[![CI](../../../actions/workflows/ci.yml/badge.svg)](../../../actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](../../../LICENSE)
[![English](https://img.shields.io/badge/English-README-blue)](README.en.md)
[![简体中文](https://img.shields.io/badge/简体中文-README-gray)](../../README.md)

[Features](#-features) · [Showcase](#-feature-showcase) · [Get Started](#-get-started) · [MCP](#mcp) · [License](#-license)

</div>

## ✨ Features

- **Three-pane browsing** — class-tree, property, and prefix-URI sidebars plus instant search; silky-smooth virtualized scrolling even on huge ontologies
- **Smart graph visualization** — canvas hosts local-neighbor and global-overview graphs, edges colored by semantics, node positions remembered after dragging
- **Point-and-edit canvas** — right-click to create, edit, and delete classes and properties, no page-hopping needed
- **Progressive canvas for huge ontologies** — past 2000 live classes the overview switches to folded roots (click the +/− badges to expand subtrees in place, with live subtree sizes); a toggle forces the full view
- **Millisecond incremental commits** — every edit patches the in-memory index at once (read-your-writes); the file lands via a debounced background save
- **Integrated source editing** — built-in editor with full find-and-replace
- **Built-in SPARQL console** — a third browse view; read-only is engine-enforced (UPDATE always rejected), SELECT/ASK/CONSTRUCT results, IRIs auto-shortened to curies
- **SHACL validation** — run built-in or custom SHACL shapes against the ontology, with severity-graded reports
- **OWL 2 compatible & profile-aware** — Manchester axiom rendering plus EL/QL/RL/DL profile detection (vocabulary-level approximation)
- **Offline docs export** — generates a static site with zero external dependencies

## 📸 Feature Showcase

**Overview page**

![Overview home](screenshots/home.png)

**Graph mode**

![Workspace graph mode](screenshots/browser-graph.png)

**Source editing**

![Source mode](screenshots/browser-text.png)

## 🚀 Get Started

### Option 1: Docker (recommended)

```bash
git clone https://github.com/skymacro111666/ontology-workbench.git
cd ontology-workbench
docker compose up -d --build
```

Open `http://<your-ip-address>:8734`. Data is kept in the project-local `./data` and `./logs` directories and survives container rebuilds. `OW_PORT=9000 docker compose up -d` sets the port; if `OW_JWT_SECRET` is unset a secret is generated on first start and saved in `data/jwt-secret`.

### Option 2: From source

Prerequisites: Python ≥ 3.11, uv, Node.js ≥ 22, and npm.

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

Open `http://<your-ip-address>:8734` (set `OW_HOST=0.0.0.0` in `.env` first — the default binds loopback only); the first visit walks you through a one-time admin setup; log in and load a bundled sample ontology. **Config precedence: CLI flags > environment variables (`.env`) > defaults**; common variables are `OW_HOST` / `OW_PORT` / `OW_DATA_DIR` / `OW_DB_URL` (SQLite by default, PostgreSQL support coming soon) / `OW_LOG_LEVEL`; the docs-site export directory is confined to `{data dir}/exports/` unless `OW_EXPORT_ALLOW_ANY_PATH=1` opts out.

## MCP

A built-in MCP server (read-only in v1): 10 tools over streamable HTTP at `/api/v1/mcp`. It mounts once the first agent token exists (restart to apply); with zero tokens the endpoint is absent (404).

### Creating an agent token

Either way works:

- **Settings page**: top-bar user menu → Agent tokens;
- **API**:

```bash
curl -X POST http://127.0.0.1:8734/api/v1/agent-tokens \
  -H "Authorization: Bearer <login token>" -H "Content-Type: application/json" \
  -d '{"label":"claude"}'
```

The plaintext token ships only in the creation response; `OW_AGENT_TOKENS="label:owag_…"` bulk-imports at first boot (for migration; the DB is authoritative afterwards).

### Connecting a client

```bash
claude mcp add --transport http ow http://127.0.0.1:8734/api/v1/mcp \
  --header "Authorization: Bearer owag_…"
```

or any MCP client that speaks streamable HTTP:

```json
{
  "mcpServers": {
    "ow": {
      "type": "http",
      "url": "http://127.0.0.1:8734/api/v1/mcp",
      "headers": { "Authorization": "Bearer owag_…" }
    }
  }
}
```

### Tool catalog (10, all read-only)

| Tool | Description |
|------|-------------|
| `list_ontologies` | Entry point: oid/title/entity counts/profile |
| `get_ontology` | Metadata: stats, prefix table, OWL 2 profile, save state |
| `search_entities` | Search over curie/label/comment, with kind filter |
| `get_entity` | Label/comment/Manchester axiom lines/references/instance count |
| `get_class_tree` | Class-tree slices; drill down by parent |
| `get_instances` | Instances of a class, assertions included |
| `run_lint` | 10 built-in rules + custom SPARQL rules |
| `run_validation` | SHACL validation (points to the UI when no shapes are saved) |
| `sparql_query` | Read-only SPARQL (engine-enforced, 1000-row cap) |
| `export_file` | Full export (200,000-byte cap; suggests sparql_query beyond it) |

Security semantics: an agent token is the account's machine credential (GitHub-PAT-shaped) — stored hashed in the DB, usable directly as a REST Bearer credential, and confined to a read-only endpoint allowlist; revocation takes effect immediately.

> All REST APIs live under `/api/v1/*` as of v0.3.0.

## 📄 License

[Apache License 2.0](../../LICENSE) · Copyright 2026 The Ontology Workbench Authors.
