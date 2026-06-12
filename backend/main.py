"""FastAPI app entrypoint: load env, configure logging, assemble routers, and serve
the built frontend. Startup/shutdown logic lives in core.lifespan; config access in
core.config; per-domain logic in services/. This file stays a thin assembly."""
import os

from dotenv import load_dotenv

load_dotenv()

from core.logging_config import configure_logging

configure_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from core.config import DIST_DIR
from core.lifespan import lifespan
from routers import profiles, meals, nutrition, config

app = FastAPI(title="AI Nutrition Tracker", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
