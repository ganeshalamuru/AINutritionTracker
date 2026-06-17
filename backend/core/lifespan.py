"""FastAPI startup/shutdown wiring, kept out of main.py so the app entrypoint stays
a thin assembly of routers. Creates tables, runs the idempotent schema migrations,
prepares the USDA food cache (purging it when the matching logic version changes),
seeds default config, and reaps stale uploads."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from sqlalchemy import text

from core import config
from core.config import CACHE_VERSION, UPLOADS_DIR
from core.database import Base, SessionLocal, engine

logger = logging.getLogger("nutriai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    _migrate_and_prepare_cache()

    db = SessionLocal()
    try:
        config.seed_defaults(db)
        # Build the vision provider clients and the USDA HTTP client once, now that config
        # is seeded. Imported locally to keep core's import graph free of services.
        from services.usda_service import reload_client as reload_usda_client
        from services.vision_service import reload_clients

        reload_clients(db)
        reload_usda_client(db)
    finally:
        db.close()

    _purge_old_uploads()
    yield
    _purge_old_uploads()


def _migrate_and_prepare_cache():
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE meals ADD COLUMN group_id TEXT"))
            conn.commit()
        except Exception:
            pass  # column already exists
        try:
            conn.execute(text("ALTER TABLE profiles ADD COLUMN calorie_goal INTEGER DEFAULT 2000"))
            conn.commit()
        except Exception:
            pass  # column already exists
        # Micros added after the initial schema (lipid panel + extra minerals/other).
        # Old meals get 0, consistent with the missing->0 coercion in core.nutrients.
        for col in (
            "selenium_mcg",
            "copper_mg",
            "choline_mg",
            "caffeine_mg",
            "saturated_fat_g",
            "mono_fat_g",
            "poly_fat_g",
            "cholesterol_mg",
            "omega3_g",
        ):
            try:
                conn.execute(text(f"ALTER TABLE micros ADD COLUMN {col} FLOAT DEFAULT 0"))
                conn.commit()
            except Exception:
                pass  # column already exists
        # Cache of USDA food-name -> per-100g nutrient lookups (see usda_service.py).
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS food_cache ("
                "query TEXT PRIMARY KEY, fdc_id INTEGER, nutrients_json TEXT, fetched_at REAL)"
            )
        )
        conn.commit()
        # Purge cached lookups when the matching logic version changes, so improved
        # matching isn't masked by stale rows from an older algorithm.
        stored = conn.execute(
            text("SELECT value FROM app_config WHERE key = 'food_cache_version'")
        ).first()
        if not stored or stored[0] != CACHE_VERSION:
            conn.execute(text("DELETE FROM food_cache"))
            conn.execute(
                text(
                    "INSERT INTO app_config (key, value) VALUES ('food_cache_version', :v) "
                    "ON CONFLICT(key) DO UPDATE SET value = :v"
                ),
                {"v": CACHE_VERSION},
            )
            conn.commit()
            logger.info("food_cache purged (version -> %s)", CACHE_VERSION)


def _purge_old_uploads():
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    for fname in os.listdir(UPLOADS_DIR):
        fpath = os.path.join(UPLOADS_DIR, fname)
        if os.path.isfile(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=UTC)
            if mtime < cutoff:
                os.remove(fpath)
