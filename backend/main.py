import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

from logging_config import configure_logging
configure_logging()

from database import engine, get_db, Base
from models import AppConfig
from schemas import ConfigUpdate
from services.gemini_service import DEFAULT_MODEL, DEFAULT_PROVIDER
from routers import profiles, meals, nutrition

logger = logging.getLogger("nutriai")

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "uploads")
DIST_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    os.makedirs(UPLOADS_DIR, exist_ok=True)

    from sqlalchemy import text
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE meals ADD COLUMN group_id TEXT"))
            conn.commit()
        except Exception:
            pass  # column already exists

    from database import SessionLocal
    db = SessionLocal()
    try:
        seeds = {
            "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
            "groq_api_key": os.getenv("GROQ_API_KEY", ""),
            "vision_provider": DEFAULT_PROVIDER,
            "vision_model": DEFAULT_MODEL,
        }
        added = False
        for key, value in seeds.items():
            if not db.query(AppConfig).filter(AppConfig.key == key).first():
                db.add(AppConfig(key=key, value=value))
                added = True
        if added:
            db.commit()
    finally:
        db.close()

    _purge_old_uploads()
    yield
    _purge_old_uploads()


def _purge_old_uploads():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    for fname in os.listdir(UPLOADS_DIR):
        fpath = os.path.join(UPLOADS_DIR, fname)
        if os.path.isfile(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            if mtime < cutoff:
                os.remove(fpath)


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


def _get_config_value(db: Session, key: str, default: str = "") -> str:
    config = db.query(AppConfig).filter(AppConfig.key == key).first()
    return config.value if config and config.value else default


def _set_config_value(db: Session, key: str, value: str):
    config = db.query(AppConfig).filter(AppConfig.key == key).first()
    if config:
        config.value = value
    else:
        db.add(AppConfig(key=key, value=value))


@app.get("/api/config")
def get_config(db: Session = Depends(get_db)):
    return {
        "gemini_api_key_set": bool(_get_config_value(db, "gemini_api_key")),
        "groq_api_key_set": bool(_get_config_value(db, "groq_api_key")),
        "vision_provider": _get_config_value(db, "vision_provider", DEFAULT_PROVIDER),
        "vision_model": _get_config_value(db, "vision_model", DEFAULT_MODEL),
    }


@app.put("/api/config")
def update_config(data: ConfigUpdate, db: Session = Depends(get_db)):
    if data.gemini_api_key is not None:
        _set_config_value(db, "gemini_api_key", data.gemini_api_key)
    if data.groq_api_key is not None:
        _set_config_value(db, "groq_api_key", data.groq_api_key)
    if data.vision_provider is not None:
        _set_config_value(db, "vision_provider", data.vision_provider)
    if data.vision_model is not None:
        _set_config_value(db, "vision_model", data.vision_model)
    db.commit()
    return {"ok": True}


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
