"""App config routes (API keys + vision provider/model), moved out of main.py.
Only exposes whether each key is set — never the key values themselves."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core import config
from core.config import DEFAULT_MODEL, DEFAULT_NUTRITION_SOURCE, DEFAULT_PROVIDER
from core.database import get_db
from schemas import ConfigStatus, ConfigUpdate, OkResponse
from services.usda_service import reload_client as reload_usda_client
from services.vision_service import reload_clients

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigStatus, summary="Config status (no secret values)")
def get_config(db: Session = Depends(get_db)):
    return {
        "gemini_api_key_set": bool(config.get_value(db, "gemini_api_key")),
        "groq_api_key_set": bool(config.get_value(db, "groq_api_key")),
        "usda_api_key_set": bool(config.get_value(db, "usda_api_key")),
        "nutrition_source": config.get_value(db, "nutrition_source", DEFAULT_NUTRITION_SOURCE),
        "vision_provider": config.get_value(db, "vision_provider", DEFAULT_PROVIDER),
        "vision_model": config.get_value(db, "vision_model", DEFAULT_MODEL),
    }


@router.put("", response_model=OkResponse, summary="Update API keys / vision provider")
def update_config(data: ConfigUpdate, db: Session = Depends(get_db)):
    for key in (
        "gemini_api_key",
        "groq_api_key",
        "usda_api_key",
        "nutrition_source",
        "vision_provider",
        "vision_model",
    ):
        value = getattr(data, key)
        if value is not None:
            config.set_value(db, key, value)
    db.commit()
    # A key/provider/model may have changed — rebuild the vision clients and the USDA
    # client so the next /analyze uses the new credentials without restarting the app.
    reload_clients(db)
    reload_usda_client(db)
    return {"ok": True}
