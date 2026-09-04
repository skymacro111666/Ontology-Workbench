# Contributing to Ontology Workbench

Thanks for your interest in improving Ontology Workbench! / 感谢你愿意为 Ontology Workbench 贡献代码!

- [Reporting bugs](#reporting-bugs) · [Requesting features](#requesting-features)
- [Development setup](#development-setup) · [Commit style](#commit-style) · [Pull requests](#pull-requests)

## Reporting bugs

Open an issue with the **Bug report** template. Always include:

1. What you did (steps to reproduce, and the ontology file if you can share it)
2. What you expected vs. what happened (screenshots help)
3. Your environment: version tag, deployment mode (Docker / pip / from source), browser

The backend logs a `request_id` with every error — paste it into the issue and we
can trace the exact failure from structured logs.

## Requesting features

Open an issue with the **Feature request** template and lead with the *use case*,
not the solution: what ontology workflow are you trying to complete? We weigh
features by how they fit the app's one-job scope — a self-hosted workbench for
browsing, editing and publishing ontologies.

## Development setup

Prerequisites: **Python ≥ 3.11** with [uv](https://docs.astral.sh/uv/), **Node 22** with npm.

```bash
git clone <your-fork> && cd ontology-workbench

# Backend — FastAPI + pyoxigraph (SQLite by default)
cd backend && uv sync

# Frontend — React 19 + Vite
cd ../frontend && npm ci

# Run: backend on :8000, frontend dev server proxies to it
cd ../backend && uv run ow serve
cd ../frontend && npm run dev

# Tests / lint (everything CI runs, nothing more)
cd backend && uv run ruff check . && uv run ruff format --check . \
  && uv run mypy ontoworkbench && uv run lint-imports && uv run pytest -q
cd ../frontend && npx eslint . && npx tsc -b --noEmit && npm run build && npx vitest run
```

A pre-commit config runs ruff and import-linter locally once installed
(`pre-commit install`). Frontend tests must run from `frontend/` — the vitest
config lives there.

**Keep npm lifecycle scripts enabled.** `npm ci` applies a carried patch to
`@antv/g-lite` (see `frontend/patches/`) fixing a stack overflow when rendering
graphs with 1000+ nodes; running with `ignore-scripts=true` skips it and large
canvases will stay blank. The patch drops out on its own once upstream ships
the fix.

**UI text is bilingual.** All user-facing copy renders through
react-i18next: add keys to `frontend/src/i18n/locales/{zh,en}.json` (keep both
files key-identical) and reference them with `t('...')` — never hardcode copy in
components. Error messages map by backend error code in the same dictionaries.

## Commit style

**Conventional commits are load-bearing here**: the GitHub Release notes are
generated automatically from commit subjects since the previous tag. Please use
`feat:`, `fix:`, `docs:`, `perf:`, `refactor:`, `test:`, `chore:` — and write
the subject so it reads well in a changelog ("add X", not "work on Y").

## Pull requests

1. Fork, create a topic branch, keep commits granular
2. Fill in the PR template (summary, type, checklist)
3. New behavior comes with tests — backend `pytest`, frontend `vitest`
4. UI changes: attach before/after screenshots, and update both locale files
5. CI must be green: backend (ruff, mypy, import-linter, pytest) and
   frontend (eslint, tsc, build, vitest)

Small, focused PRs get reviewed fast. If a change is big, open an issue first
so we can agree on the approach.

## License

By contributing you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE) that covers this repository.

---

## 中文速览

- **报 bug / 提需求**:用对应的 issue 模板;报 bug 请附复现步骤、期望与实际差异、环境(版本/部署方式/浏览器),以及后端日志里的 `request_id`
- **本地开发**:Python ≥3.11 + uv,Node 22;后端 `uv sync` + `uv run ow serve`,前端 `npm ci` + `npm run dev`;测试与 lint 命令以 CI 为准(见上文代码块)
- **界面文案必须走 i18n**:键同时加进 `zh.json` 与 `en.json`,组件里用 `t('...')`,不要硬编码文案;错误文案按后端错误码入字典
- **提交信息用 conventional commits**(`feat:`/`fix:`/…):Release 说明由提交记录自动生成,subject 要能直接当 changelog 条目读
- **PR 要求**:带测试、CI 全绿;UI 改动附前后截图并同步双语字典;大改动先开 issue 对齐方案
- 贡献即同意以仓库的 [Apache 2.0](LICENSE) 许可发布
