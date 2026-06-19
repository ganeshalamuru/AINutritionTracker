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
        _migrate_split_to_nutrients(conn)
        _migrate_profiles_to_users(conn)
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


def _slugify_username(name: str, taken: set[str]) -> str:
    """Derive a unique, valid username from a display name: lowercase, keep [a-z0-9_.-],
    pad to >=3 chars, and suffix with a number on collision. Matches schemas.UsernameField."""
    import re

    base = re.sub(r"[^a-z0-9_.-]", "", (name or "").lower()) or "user"
    if len(base) < 3:
        base = (base + "user")[:3]
    base = base[:32]
    candidate = base
    n = 1
    while candidate in taken:
        suffix = str(n)
        candidate = base[: 32 - len(suffix)] + suffix
        n += 1
    taken.add(candidate)
    return candidate


def _migrate_profiles_to_users(conn):
    """Migrate legacy PIN profiles to user accounts (idempotent).

    Adds the auth columns (username/password_hash/role/must_change_password) to the existing
    `profiles` table, then for any pre-auth row (carrying the old `pin`, no username yet):
    derives a username from the name, sets the PIN as the temporary bcrypt password with
    must_change_password=1, and promotes the oldest profile to admin if none exists. Finally
    drops the now-unused NOT NULL `pin` column so new ORM inserts (which omit it) don't fail.

    No-op on fresh DBs (Base.metadata.create_all already built the new schema; the ALTERs and
    the pin DROP are caught) and on already-migrated DBs (every row has a username)."""
    # core.security imports bcrypt + core.config; import locally so core's module-import graph
    # stays free of the heavier crypto dep until startup actually needs it.
    from core.security import hash_password

    for ddl in (
        "ALTER TABLE profiles ADD COLUMN username TEXT",
        "ALTER TABLE profiles ADD COLUMN password_hash TEXT",
        "ALTER TABLE profiles ADD COLUMN role TEXT DEFAULT 'user'",
        "ALTER TABLE profiles ADD COLUMN must_change_password INTEGER DEFAULT 0",
    ):
        try:
            conn.execute(text(ddl))
            conn.commit()
        except Exception:
            pass  # column already exists

    cols = {row[1] for row in conn.execute(text("PRAGMA table_info(profiles)")).fetchall()}
    has_pin = "pin" in cols

    # Backfill credentials for rows that predate auth (only possible when the legacy pin exists).
    if has_pin:
        rows = conn.execute(
            text("SELECT id, name, pin FROM profiles WHERE username IS NULL ORDER BY id")
        ).fetchall()
        if rows:
            taken = {
                r[0]
                for r in conn.execute(
                    text("SELECT username FROM profiles WHERE username IS NOT NULL")
                ).fetchall()
                if r[0]
            }
            for pid, name, pin in rows:
                username = _slugify_username(name or "", taken)
                conn.execute(
                    text(
                        "UPDATE profiles SET username = :u, password_hash = :ph, "
                        "must_change_password = 1 WHERE id = :id"
                    ),
                    {"u": username, "ph": hash_password(str(pin or "0000")), "id": pid},
                )
            conn.commit()
            logger.info("migrated %d PIN profile(s) -> user accounts", len(rows))

    # Ensure exactly one admin exists if there are any users (the oldest becomes admin).
    has_admin = conn.execute(text("SELECT 1 FROM profiles WHERE role = 'admin' LIMIT 1")).first()
    if not has_admin:
        oldest = conn.execute(text("SELECT id FROM profiles ORDER BY id LIMIT 1")).first()
        if oldest:
            conn.execute(
                text("UPDATE profiles SET role = 'admin' WHERE id = :id"), {"id": oldest[0]}
            )
            conn.commit()
            logger.info("promoted profile id=%s to admin", oldest[0])

    # Enforce username uniqueness (create_all already does this on fresh DBs).
    try:
        conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS uq_profiles_username ON profiles(username)")
        )
        conn.commit()
    except Exception:
        logger.exception("could not create unique username index")

    # Drop the legacy NOT NULL `pin` column so new accounts (which don't set it) can insert.
    if has_pin:
        try:
            conn.execute(text("ALTER TABLE profiles DROP COLUMN pin"))
            conn.commit()
            logger.info("dropped legacy profiles.pin column")
        except Exception:
            logger.exception("could not drop legacy profiles.pin column")


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
