"""FastAPI app entrypoint: load env, configure logging, assemble routers, and serve
the built frontend. Startup/shutdown logic lives in core.lifespan; config access in
core.config; per-domain logic in services/. This file stays a thin assembly."""

import logging
import os
import time

from dotenv import load_dotenv

load_dotenv()

from core.logging_config import configure_logging

configure_logging()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from scalar_fastapi import get_scalar_api_reference
from sqlalchemy import text

from core.config import DIST_DIR
from core.database import engine
from core.lifespan import lifespan
from core.request_context import new_request_id, request_id_var, user_id_var
from routers import admin, auth, config, foods, meals, nutrition, users

logger = logging.getLogger("nutriai")

_app_env = os.getenv("APP_ENV", "development").lower()

# Sentry error tracking — initialized only when SENTRY_DSN is set, so local/dev runs with no
# DSN are unaffected and no DSN is ever hardcoded. Must run before the app is created so the
# auto-enabled FastAPI/Starlette integrations wrap it. Errors flow to Sentry in addition to the
# existing logging + global exception handler. send_default_pii stays off (no request bodies/keys).
_sentry_dsn = os.getenv("SENTRY_DSN")
if _sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=_sentry_dsn,
        environment=_app_env,
        traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.0")),
        send_default_pii=False,
    )
    logger.info("Sentry error tracking enabled (environment=%s)", _app_env)

# Interactive docs are on by default (local/dev convenience) and hidden when the app is
# run as a shared deployment — set APP_ENV=production to disable /docs, /redoc, /openapi.json
# (and, with them, the dev-only /api/admin/* data-inspection routes).
_docs_on = _app_env != "production"

# Per-tag descriptions surfaced in the Swagger UI sidebar.
_openapi_tags = [
    {"name": "auth", "description": "Register, log in, refresh tokens, change password."},
    {"name": "users", "description": "Own account settings + admin user management."},
    {"name": "meals", "description": "Analyze a photo, log meals/groups, browse the timeline."},
    {"name": "nutrition", "description": "Daily and monthly nutrition rollups."},
    {"name": "config", "description": "API keys, vision provider/model, and nutrition source."},
    {"name": "foods", "description": "Search the offline USDA index and fetch per-100g nutrients."},
    {
        "name": "admin",
        "description": "Dev-only: inspect both SQLite DBs (read-only SQL console + views).",
    },
    {"name": "health", "description": "Liveness probe."},
]
app = FastAPI(
    title="AI Nutrition Tracker",
    description=(
        "Two-stage nutrition tracker: a vision LLM identifies dishes/ingredients, then USDA "
        "FoodData Central (offline local index or live API) supplies the macro/micro numbers. "
        "Interactive docs at /docs; admin endpoints are available outside production only."
    ),
    version="1.0.0",
    openapi_tags=_openapi_tags,
    lifespan=lifespan,
    docs_url="/docs" if _docs_on else None,
    redoc_url="/redoc" if _docs_on else None,
    openapi_url="/openapi.json" if _docs_on else None,
)

# The frontend is served same-origin (prod: FastAPI serves dist/ on :8000; dev: Vite
# proxies /api -> :8001), so cross-origin requests aren't part of normal operation and
# CORS stays locked down by default. Set CORS_ORIGINS (comma-separated) to allow specific
# origins — e.g. a separate dev server pointed straight at the API.
_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,  # the refresh-token cookie must ride cross-origin when configured
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Bind a request id (trace id) and the caller's user id for the duration of the
    request so every downstream log line is correlated, then emit one access-log line with
    method/path/status/duration. The request id is taken from an inbound X-Request-ID
    (lets a proxy/client supply its own trace) or generated, and echoed back on the
    response. The user id comes from the X-User-Id header the frontend sends on every
    call. Both are reset in `finally` so values never bleed across requests."""
    req_id = request.headers.get("x-request-id") or new_request_id()
    user_id = request.headers.get("x-user-id", "-")
    req_token = request_id_var.set(req_id)
    user_token = user_id_var.set(user_id)
    start = time.perf_counter()
    response = None
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response
    finally:
        # Emit one correlated access line in `finally` so requests that raise are logged too
        # (a raise becomes a 500 via the exception handler). uvicorn's own access log is
        # disabled in core.logging_config. Include the query string + client IP so nothing
        # uvicorn logged is lost. Query strings here carry no secrets (user_id/dates/paging
        # only; keys travel in the body/headers). In dev the client IP is the Vite proxy.
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        client_host = request.client.host if request.client else "-"
        logger.info(
            "%s %s -> %d (%.0f ms) from %s",
            request.method,
            path,
            response.status_code if response is not None else 500,
            (time.perf_counter() - start) * 1000,
            client_host,
        )
        request_id_var.reset(req_token)
        user_id_var.reset(user_token)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler: log the unexpected error and return a clean 500. FastAPI
    still handles HTTPException (the explicit error mapping in meal_service) separately."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health", tags=["health"], summary="Health check")
async def health():
    """Liveness probe — the process is up. Used by the Docker HEALTHCHECK and Koyeb."""
    return {"status": "ok"}


@app.get("/api/health/ready", tags=["health"], summary="Readiness check")
async def health_ready():
    """Readiness probe — the process can reach its database. Returns 503 if a `SELECT 1`
    against the app DB fails, so an orchestrator can hold traffic until the DB is reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("readiness check failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ready"}


# Prometheus metrics at /metrics (scrapeable text). instrument() adds the timing middleware and
# expose() registers the route; both run here at import time, before the catch-all serve_react
# route below, so /metrics isn't swallowed (same ordering concern noted for /scalar). Opt out
# with METRICS_ENABLED=0.
if os.getenv("METRICS_ENABLED", "1").lower() not in ("0", "false", "no"):
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)


# Scalar API reference — an alternative to Swagger UI (/docs) / ReDoc (/redoc), driven by the
# same /openapi.json schema. Gated on the same APP_ENV switch (openapi_url is None in production,
# so this is hidden alongside the others). Declared before the catch-all serve_react route so it
# isn't swallowed. telemetry off to keep with the app's fully-local posture.
if _docs_on:

    @app.get("/scalar", include_in_schema=False)
    async def scalar_docs():
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title=app.title,
            telemetry=False,
        )


app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(meals.router, prefix="/api")
app.include_router(nutrition.router, prefix="/api")
app.include_router(config.router, prefix="/api")
# Foods search is public (USDA data); the admin data-inspection API is dev-only — mounting it
# only when docs are on keeps it out of the schema and unreachable in production.
app.include_router(foods.router, prefix="/api")
if _docs_on:
    app.include_router(admin.router, prefix="/api")


if os.path.exists(DIST_DIR):
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_react(full_path: str):
    # Unknown /api paths must not fall through to the SPA shell (which would return 200 HTML
    # to an API client); return a JSON 404 instead. Real API routes are registered above.
    if full_path == "api" or full_path.startswith("api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    index = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {
        "message": "Frontend not built yet. Run: cd frontend && npm install && npm run build",
        "api_docs": "/docs",
    }
