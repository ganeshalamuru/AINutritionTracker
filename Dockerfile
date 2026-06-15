# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 — build the React frontend into static files (frontend/dist).
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend
WORKDIR /frontend

# Install deps from the lockfile first (cached unless package*.json changes).
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build the static bundle -> /frontend/dist
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Python runtime. uv installs the locked deps; FastAPI serves the
# built frontend + the API on port 8000 (same single-origin layout as local).
# ---------------------------------------------------------------------------
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS runtime

# uv: compile bytecode for faster cold start, copy (not symlink) into the venv, and
# never fetch a managed Python (use the image's). Production defaults: docs/admin off,
# and online USDA since the offline FTS5 index (usda_local.db) isn't baked into the image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    APP_ENV=production \
    NUTRITION_SOURCE=online \
    PATH="/app/backend/.venv/bin:$PATH"

WORKDIR /app/backend

# Install dependencies first, from only the manifest + lock, so this layer is cached
# across source changes. package=false (pyproject) means the app itself isn't installed.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

# App source + the built frontend, placed where DIST_DIR (backend/../frontend/dist) expects it.
COPY backend/ ./
COPY --from=frontend /frontend/dist /app/frontend/dist

# Drop root; create the uploads dir the app writes to.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/backend/uploads \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Liveness probe (mirrors the readiness endpoint the orchestrator should use externally).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
