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
from core.nutrients import NUTRIENT_KEYS

logger = logging.getLogger("nutriai")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Rename the legacy account schema (profiles -> users, meals.profile_id -> user_id) BEFORE
    # create_all, so create_all doesn't build an empty `users` table beside the old `profiles`.
    _migrate_legacy_schema()
    Base.metadata.create_all(bind=engine)
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    _migrate_and_prepare_cache()

    db = SessionLocal()
    try:
        config.seed_defaults(db)
        # Build the vision provider clients and the USDA HTTP client once, now that config
        # is seeded. Imported locally to keep core's import graph free of services.
        # init_clients builds the never-rebuilt pools (Groq httpx pool, Ollama); reload_clients
        # then builds the keyed Gemini model (the Groq key is injected per request, not cached).
        from services.usda_service import reload_client as reload_usda_client
        from services.vision_service import init_clients, reload_clients

        init_clients()
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
            conn.execute(text("ALTER TABLE users ADD COLUMN calorie_goal INTEGER DEFAULT 2000"))
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
        _migrate_split_to_nutrients(conn)
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


def _migrate_legacy_schema():
    """Rename the legacy account schema in place, preserving data, before create_all builds the
    ORM tables. The account table was historically named `profiles` and meals referenced it via
    a `profile_id` FK; both are now `users` / `user_id`.

    Idempotent and guarded by existence checks: on a fresh DB nothing exists yet, so every step
    is a no-op and create_all builds `users` directly; on an already-renamed DB the guards skip.
    SQLite updates child-table FK references automatically when a table is renamed
    (legacy_alter_table is off by default)."""
    with engine.connect() as conn:

        def _table_exists(name: str) -> bool:
            return (
                conn.execute(
                    text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": name}
                ).first()
                is not None
            )

        if _table_exists("profiles") and not _table_exists("users"):
            conn.execute(text("ALTER TABLE profiles RENAME TO users"))
            conn.commit()
            logger.info("renamed legacy table profiles -> users")

        if _table_exists("meals"):
            cols = {row[1] for row in conn.execute(text("PRAGMA table_info(meals)")).fetchall()}
            if "profile_id" in cols and "user_id" not in cols:
                conn.execute(text("ALTER TABLE meals RENAME COLUMN profile_id TO user_id"))
                conn.commit()
                logger.info("renamed legacy column meals.profile_id -> meals.user_id")

        # Normalize the username index name: indexes keep their old names through a table rename,
        # so a migrated DB carries `*_profiles_username` indexes on the renamed table. Drop them
        # and recreate the canonical `ix_users_username` (what create_all emits on a fresh DB), so
        # the schema — and the admin SQL console — is free of 'profiles'. create_all won't add
        # indexes to an already-existing table, so do it here.
        try:
            conn.execute(text("DROP INDEX IF EXISTS uq_profiles_username"))
            conn.execute(text("DROP INDEX IF EXISTS ix_profiles_username"))
            if _table_exists("users"):
                conn.execute(
                    text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username)")
                )
            conn.commit()
        except Exception:
            logger.exception("could not normalize the username index")


def _migrate_split_to_nutrients(conn):
    """One-time copy of the legacy split macros+micros rows into the merged `nutrients`
    table (created by Base.metadata.create_all). Idempotent — only copies meals not yet
    present in `nutrients`, so it's a no-op on every run after the first and on fresh DBs
    (no `macros` table). The old `macros`/`micros` tables are left untouched so the
    migration stays fully reversible; the ORM simply no longer maps them.

    The 7 headline-macro keys come from the old `macros` table, the remaining 24 from
    `micros`; values are COALESCEd to 0 to match the missing->0 coercion in core.nutrients."""
    # Fresh DB (or already-migrated DB whose legacy tables were never created): nothing to do.
    # We check for the table rather than swallowing all errors, so a *genuine* migration failure
    # surfaces loudly instead of silently leaving real logged meals stranded in the old tables.
    has_macros = conn.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name='macros'")
    ).first()
    if not has_macros:
        return

    macro_keys = NUTRIENT_KEYS[:7]  # calories..sodium_mg lived in `macros`
    micro_keys = NUTRIENT_KEYS[7:]  # everything else lived in `micros`
    cols = ", ".join(NUTRIENT_KEYS)
    selects = ", ".join([f"COALESCE(ma.{k}, 0)" for k in macro_keys])
    selects += ", " + ", ".join([f"COALESCE(mi.{k}, 0)" for k in micro_keys])
    result = conn.execute(
        text(
            f"INSERT INTO nutrients (meal_id, {cols}) "
            f"SELECT ma.meal_id, {selects} "
            "FROM macros ma LEFT JOIN micros mi ON ma.meal_id = mi.meal_id "
            "WHERE ma.meal_id NOT IN (SELECT meal_id FROM nutrients)"
        )
    )
    conn.commit()
    if result.rowcount:
        logger.info("migrated %d meal(s) from split macros/micros -> nutrients", result.rowcount)


def _purge_old_uploads():
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    for fname in os.listdir(UPLOADS_DIR):
        fpath = os.path.join(UPLOADS_DIR, fname)
        if os.path.isfile(fpath):
            mtime = datetime.fromtimestamp(os.path.getmtime(fpath), tz=UTC)
            if mtime < cutoff:
                os.remove(fpath)
