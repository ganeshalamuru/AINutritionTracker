"""Single home for reading/writing the `app_config` key-value table.

Before this module the same get/set helpers were copy-pasted in main.py and
meals.py, and the vision defaults were defined in the vision service. Centralizing
them here means routers and services share one implementation and the startup
seeder, the /api/config endpoints, and the vision dispatch all agree on defaults.
"""

import os

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import AppConfig

# Filesystem paths, resolved relative to the backend/ directory (this file lives in
# backend/core/). Single definition shared by the lifespan, meal service, and main.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BACKEND_DIR, "uploads")
DIST_DIR = os.path.join(BACKEND_DIR, "..", "frontend", "dist")

# Default vision provider/model (seeded into app_config on first launch and used as
# the fallback when a request doesn't specify one). Groq's free tier gives
# ~1,000 RPD / 6K TPM — far more usable than Google's ~20 RPD on Flash. Llama 4
# Scout is natively multimodal.
DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

DEFAULT_USDA_KEY = "DEMO_KEY"

# Where Stage 2 gets its nutrient numbers: "offline" -> local SQLite FTS5 index
# (backend/usda_local.db, built by build_usda_db.py), "online" -> the USDA FoodData Central
# API. Defaults to offline (no network, no rate limits); switchable in Settings.
DEFAULT_NUTRITION_SOURCE = "offline"

# Version of the USDA food-cache contents. BUMP THIS whenever the matching/alias logic
# (services/usda_service.py + services/nutrition_data/) changes, so stale cached lookups
# are discarded. core/lifespan.py purges food_cache on startup when the stored version differs.
CACHE_VERSION = "11"


def get_value(db: Session, key: str, default: str = "") -> str:
    config = db.query(AppConfig).filter(AppConfig.key == key).first()
    return config.value if config and config.value else default


def set_value(db: Session, key: str, value: str):
    config = db.query(AppConfig).filter(AppConfig.key == key).first()
    if config:
        config.value = value
    else:
        db.add(AppConfig(key=key, value=value))


def get_api_key(db: Session, provider: str = "gemini") -> str:
    """The configured key for a vision provider, or a 503 telling the user to set it.
    Ollama runs locally with no key, so it needs no guard."""
    if provider == "ollama":
        return ""
    key_name = "groq_api_key" if provider == "groq" else "gemini_api_key"
    label = "Groq" if provider == "groq" else "Gemini"
    value = get_value(db, key_name)
    if not value:
        raise HTTPException(
            status_code=503,
            detail=f"{label} API key not configured. Go to Settings to add your key.",
        )
    return value


def get_vision_config(db: Session) -> tuple[str, str]:
    """(provider, model) for vision analysis, falling back to the defaults."""
    return (
        get_value(db, "vision_provider", DEFAULT_PROVIDER),
        get_value(db, "vision_model", DEFAULT_MODEL),
    )


def get_usda_key(db: Session) -> str:
    return get_value(db, "usda_api_key", DEFAULT_USDA_KEY)


def get_nutrition_source(db: Session) -> str:
    """'offline' (local FTS5 index) or 'online' (USDA API). Read by usda_service.reload_client
    to select the Stage-2 backend at startup and on every config change."""
    return get_value(db, "nutrition_source", DEFAULT_NUTRITION_SOURCE)


def seed_defaults(db: Session):
    """Insert config rows that don't exist yet (first launch). Keys are seeded from
    env vars where available so a fresh deployment can be configured without the UI."""
    seeds = {
        "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
        "groq_api_key": os.getenv("GROQ_API_KEY", ""),
        "usda_api_key": os.getenv("USDA_API_KEY", DEFAULT_USDA_KEY),
        "nutrition_source": os.getenv("NUTRITION_SOURCE", DEFAULT_NUTRITION_SOURCE),
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
