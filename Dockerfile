# Ontology Workbench — single image: FastAPI backend serving the built SPA.
# Layout inside the container mirrors the repo (/app/{backend,frontend})
# because default_spa_dist() resolves <app.py>/../../../frontend/dist, and
# the editable uv install keeps app.py in the source tree.

# ---- stage 1: build the SPA --------------------------------------------
FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ---- stage 2: backend deps via uv (editable project install) ----------
FROM python:3.14-slim AS backend-deps
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /uvx /usr/local/bin/
# PyPI mirror by default (pypi.org is unreachable from CN networks);
# override for official: --build-arg PYPI_INDEX_URL=https://pypi.org/simple
ARG PYPI_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV UV_INDEX_URL=$PYPI_INDEX_URL
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/.env.example ./
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/ontoworkbench ./ontoworkbench
RUN uv sync --frozen --no-dev

# ---- stage 3: runtime ---------------------------------------------------
FROM python:3.14-slim
WORKDIR /app
COPY --from=backend-deps /app/backend /app/backend
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh
ENV OW_DATA_DIR=/data OW_LOG_DIR=/logs
EXPOSE 8734
ENTRYPOINT ["/entrypoint.sh"]
CMD ["/app/backend/.venv/bin/ow", "serve", "--host", "0.0.0.0", "--no-browser"]
