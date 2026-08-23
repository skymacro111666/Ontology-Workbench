# Ontology Workbench v0.1.0

First release — Phase 1 read-side workbench: upload, browse, search, and
visualize OWL ontologies, plus one-click static docs-site export.
Self-hosted, single binary-ish stack: FastAPI + React 19, Apache-2.0.

## Features

- **Parse & upload** — Turtle / RDF-XML / JSON-LD, up to 150MB; format
  sniffing by extension with content fallback; duplicate filenames
  rejected per owner (409 `DUPLICATE_FILENAME`)
- **Browse** — lazy-loaded class tree; entity pages with multilingual
  labels, comments, parents/children, property tables; raw Turtle view;
  back-references ("who points at me")
- **Search** — instant (debounced) substring search over labels, local
  names, and comments, with matched-field badges
- **Graph views** — tri-mode content area (detail / split / graph) with
  local neighbor graphs (React Flow, semantic edge styling), plus a
  whole-ontology overview that degrades to the top 3 levels above 500
  entities
- **Docs-site export** — one-click Jinja2 static site with collapsible
  tree navigation, client-side search, and dark mode; available from the
  UI, REST API, and CLI
- **Auth** — one-shot `/setup`, JWT bearer tokens (7 days, argon2id)
- **Operations** — SQLite registry (PostgreSQL-switchable via `OW_DB_URL`),
  structlog JSON logs with daily rotation (15-day retention, stdout +
  file dual sink), Prometheus `/metrics`, `X-Request-ID` propagated
  across response headers, bodies, and logs
- **CLI** — `ow serve / ow import / ow export-site`; default port 8734

## Known limitations

- SKOS vocabularies render on a best-effort basis only
- Read-only release: editing arrives in Phase 2

## Deploy from source

```bash
git clone https://github.com/skymacro111666/Ontology-Workbench.git
cd Ontology-Workbench

# backend (Python 3.11+, managed by uv)
cd backend && uv sync && cd ..

# frontend (Node 22+)
cd frontend && npm ci && npm run build && cd ..

# run (first start writes backend/.env and generates a JWT secret)
cd backend && uv run ow serve
# open http://127.0.0.1:8734 → /setup creates the admin account
```
