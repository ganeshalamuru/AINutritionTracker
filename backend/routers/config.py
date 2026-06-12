"""App config routes (API keys + vision provider/model), moved out of main.py.
Only exposes whether each key is set — never the key values themselves."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core import config
from core.config import DEFAULT_PROVIDER, DEFAULT_MODEL
from core.database import get_db
from schemas import ConfigUpdate

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
def get_config(db: Session = Depends(get_db)):
    return {
        "gemini_api_key_set": bool(config.get_value(db, "gemini_api_key")),
        "groq_api_key_set": bool(config.get_value(db, "groq_api_key")),
        "usda_api_key_set": bool(config.get_value(db, "usda_api_key")),
        "vision_provider": config.get_value(db, "vision_provider", DEFAULT_PROVIDER),
        "vision_model": config.get_value(db, "vision_model", DEFAULT_MODEL),
    }


@router.put("")
def update_config(data: ConfigUpdate, db: Session = Depends(get_db)):
    for key in ("gemini_api_key", "groq_api_key", "usda_api_key", "vision_provider", "vision_model"):
        value = getattr(data, key)
        if value is not None:
            config.set_value(db, key, value)
    db.commit()
    return {"ok": True}
