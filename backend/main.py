import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

load_dotenv()

from database import engine, get_db, Base
from models import AppConfig
from schemas import ConfigUpdate
from routers import profiles, meals, nutrition

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
        if not db.query(AppConfig).filter(AppConfig.key == "gemini_api_key").first():
            env_key = os.getenv("GEMINI_API_KEY", "")
            db.add(AppConfig(key="gemini_api_key", value=env_key))
            db.commit()
    finally:
        db.close()

    _purge_old_uploads()
    yield
    _purge_old_uploads()


def _purge_old_uploads():
    cutoff = datetime.utcnow() - timedelta(hours=1)
    for fname in os.listdir(UPLOADS_DIR):
        fpath = os.path.join(UPLOADS_DIR, fname)
        if os.path.isfile(fpath):
            mtime = datetime.utcfromtimestamp(os.path.getmtime(fpath))
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


@app.get("/api/config")
def get_config(db: Session = Depends(get_db)):
    config = db.query(AppConfig).filter(AppConfig.key == "gemini_api_key").first()
    has_key = bool(config and config.value)
    return {"gemini_api_key_set": has_key}


@app.put("/api/config")
def update_config(data: ConfigUpdate, db: Session = Depends(get_db)):
    config = db.query(AppConfig).filter(AppConfig.key == "gemini_api_key").first()
    if config:
        config.value = data.gemini_api_key
    else:
        db.add(AppConfig(key="gemini_api_key", value=data.gemini_api_key))
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
