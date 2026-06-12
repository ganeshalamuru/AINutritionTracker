"""FastAPI startup/shutdown wiring, kept out of main.py so the app entrypoint stays
a thin assembly of routers. Creates tables, runs the idempotent schema migrations,
prepares the USDA food cache (purging it when the matching logic version changes),
seeds default config, and reaps stale uploads."""
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from sqlalchemy import text

from core import config
from core.config import UPLOADS_DIR
from core.database import engine, SessionLocal, Base

logger = logging.getLogger("nutriai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    _migrate_and_prepare_cache()

    db = SessionLocal()
    try:
        config.seed_defaults(db)
    finally:
        db.close()

    _purge_old_uploads()
    yield
    _purge_old_uploads()


def _migrate_and_prepare_cache():
    # Imported here (not at module load) to avoid pulling the USDA service into the
    # import graph before the app is assembled.
    from services.usda_service import CACHE_VERSION

    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE meals ADD COLUMN group_id TEXT"))
            conn.commit()
        except Exception:
            pass  # column already exists
        # Cache of USDA food-name -> per-100g nutrient lookups (see usda_service.py).
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS food_cache ("
            "query TEXT PRIMARY KEY, fdc_id INTEGER, nutrients_json TEXT, fetched_at REAL)"
        ))
        conn.commit()
        # Purge cached lookups when the matching logic version changes, so improved
        # matching isn't masked by stale rows from an older algorithm.
        stored = conn.execute(
            text("SELECT value FROM app_config WHERE key = 'food_cache_version'")
        ).first()
        if not stored or stored[0] != CACHE_VERSION:
            conn.execute(text("DELETE FROM food_cache"))
            conn.execute(text(
                "INSERT INTO app_config (key, value) VALUES ('food_cache_version', :v) "
                "ON CONFLICT(key) DO UPDATE SET value = :v"
            ), {"v": CACHE_VERSION})
            conn.commit()
            logger.info("food_cache purged (version -> %s)", CACHE_VERSION)


def _purge_old_uploads():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    for fname in os.listdir(UPLOADS_DIR):
        fpath = os.path.join(UPLOADS_DIR, fname)
        if os.path.isfile(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=timezone.utc)
            if mtime < cutoff:
                os.remove(fpath)
