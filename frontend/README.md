# Ontology Workbench — frontend

React 19 + Vite + AntD v6 SPA for the self-hosted ontology workbench.

## Commands

```bash
npm install        # install dependencies
npm run dev        # dev server with /api proxied to 127.0.0.1:8734
npm run lint       # ESLint (flat config, typescript-eslint + react-hooks)
npm run test       # vitest (jsdom, sequential single fork)
npm run build      # tsc -b && vite build -> dist/
npm run format     # prettier --write .
```

The backend must be running (`ow serve`, port 8734) for `npm run dev`.
See the repository root README for the full architecture.
