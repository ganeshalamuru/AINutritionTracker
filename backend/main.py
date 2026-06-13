"""FastAPI app entrypoint: load env, configure logging, assemble routers, and serve
the built frontend. Startup/shutdown logic lives in core.lifespan; config access in
core.config; per-domain logic in services/. This file stays a thin assembly."""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

from core.logging_config import configure_logging

configure_logging()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import DIST_DIR
from core.lifespan import lifespan
from routers import config, meals, nutrition, profiles

logger = logging.getLogger("nutriai")

# Interactive docs are on by default (local/dev convenience) and hidden when the app is
# run as a shared deployment — set APP_ENV=production to disable /docs, /redoc, /openapi.json.
_docs_on = os.getenv("APP_ENV", "development").lower() != "production"
app = FastAPI(
    title="AI Nutrition Tracker",
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
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Last-resort handler: log the unexpected error and return a clean 500. FastAPI
    still handles HTTPException (the explicit error mapping in meal_service) separately."""
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health")
async def health():
    return {"status": "ok"}


app.include_router(profiles.router, prefix="/api")
app.include_router(meals.router, prefix="/api")
app.include_router(nutrition.router, prefix="/api")
app.include_router(config.router, prefix="/api")


if os.path.exists(DIST_DIR):
    assets_dir = os.path.join(DIST_DIR, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/{full_path:path}")
async def serve_react(full_path: str):
    index = os.path.join(DIST_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {
        "message": "Frontend not built yet. Run: cd frontend && npm install && npm run build",
        "api_docs": "/docs",
    }
