import os
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy import func
from database import get_db
from models import Meal, Macros, Micros, AppConfig
from schemas import (
    AnalyzeResponse, MealLogRequest, MealLogResponse,
    MealPatch, MealDetail, MealSummary, TimelineResponse,
    MacrosData, MicrosData
)
from services.gemini_service import analyze_meal_image

router = APIRouter(prefix="/meals", tags=["meals"])

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")


def get_api_key(db: Session) -> str:
    config = db.query(AppConfig).filter(AppConfig.key == "gemini_api_key").first()
    if not config or not config.value:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key not configured. Go to Settings to add your key."
        )
    return config.value


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_meal(
    image: UploadFile = File(...),
    profile_id: int = Form(default=0),
    db: Session = Depends(get_db)
):
    api_key = get_api_key(db)

    image_bytes = await image.read()
    token = str(uuid.uuid4())
    temp_path = os.path.join(UPLOADS_DIR, f"{token}.jpg")
    with open(temp_path, "wb") as f:
        f.write(image_bytes)

    try:
        result = analyze_meal_image(image_bytes, api_key)
    except Exception as e:
        os.remove(temp_path)
        err = str(e).lower()
        if "quota" in err or "429" in err or "rate" in err:
            raise HTTPException(status_code=429, detail="Gemini free quota hit — wait 60 seconds and try again.")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {str(e)}")

    macros = MacrosData(**result.get("macros", {}))
    micros = MicrosData(**result.get("micros", {}))

    return AnalyzeResponse(
        meal_name=result.get("meal_name", "Unknown meal"),
        meal_type=result.get("meal_type", "snack"),
        confidence=result.get("confidence", "medium"),
        estimated_serving=result.get("estimated_serving"),
        macros=macros,
        micros=micros,
        temp_image_token=token,
        notes=result.get("notes"),
    )


@router.post("/log", response_model=MealLogResponse)
def log_meal(data: MealLogRequest, db: Session = Depends(get_db)):
    if data.profile_id == 0:
        raise HTTPException(status_code=400, detail="Guest cannot log meals")

    image_path = None
    if data.temp_image_token and data.keep_image:
        temp_path = os.path.join(UPLOADS_DIR, f"{data.temp_image_token}.jpg")
        if os.path.exists(temp_path):
            image_path = f"uploads/{data.temp_image_token}.jpg"

    meal = Meal(
        profile_id=data.profile_id,
        meal_name=data.meal_name,
        meal_type=data.meal_type,
        image_path=image_path,
        notes=data.notes,
    )
    db.add(meal)
    db.flush()

    macros = Macros(meal_id=meal.id, **data.macros.model_dump())
    micros = Micros(meal_id=meal.id, **data.micros.model_dump())
    db.add(macros)
    db.add(micros)
    db.commit()

    if data.temp_image_token and not data.keep_image:
        temp_path = os.path.join(UPLOADS_DIR, f"{data.temp_image_token}.jpg")
        if os.path.exists(temp_path):
            os.remove(temp_path)

    db.refresh(meal)
    return MealLogResponse(id=meal.id, logged_at=meal.logged_at)


@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    profile_id: int,
    page: int = 1,
    limit: int = 20,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db)
):
    query = (
        db.query(Meal)
        .filter(Meal.profile_id == profile_id)
        .order_by(Meal.logged_at.desc())
    )
    if date_from:
        query = query.filter(Meal.logged_at >= date_from)
    if date_to:
        query = query.filter(Meal.logged_at <= date_to)

    total = query.count()
    meals = query.offset((page - 1) * limit).limit(limit).all()

    items = []
    for m in meals:
        macros = m.macros
        items.append(MealSummary(
            id=m.id,
            meal_name=m.meal_name,
            meal_type=m.meal_type,
            logged_at=m.logged_at,
            calories=macros.calories if macros else 0,
            protein_g=macros.protein_g if macros else 0,
            carbs_g=macros.carbs_g if macros else 0,
            fat_g=macros.fat_g if macros else 0,
            has_image=m.image_path is not None,
        ))

    return TimelineResponse(items=items, total=total, page=page, limit=limit)


@router.get("/{meal_id}", response_model=MealDetail)
def get_meal(meal_id: int, db: Session = Depends(get_db)):
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    macros = meal.macros or Macros()
    micros = meal.micros or Micros()
    return MealDetail(
        id=meal.id,
        meal_name=meal.meal_name,
        meal_type=meal.meal_type,
        logged_at=meal.logged_at,
        notes=meal.notes,
        has_image=meal.image_path is not None,
        macros=MacrosData(**{c.name: getattr(macros, c.name) for c in Macros.__table__.columns if c.name not in ("id", "meal_id")}),
        micros=MicrosData(**{c.name: getattr(micros, c.name) for c in Micros.__table__.columns if c.name not in ("id", "meal_id")}),
    )


@router.patch("/{meal_id}")
def patch_meal(meal_id: int, data: MealPatch, db: Session = Depends(get_db)):
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    if data.meal_name is not None:
        meal.meal_name = data.meal_name
    if data.meal_type is not None:
        meal.meal_type = data.meal_type
    if data.notes is not None:
        meal.notes = data.notes
    db.commit()
    return {"ok": True}


@router.delete("/{meal_id}")
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    if meal.image_path:
        full_path = os.path.join(os.path.dirname(__file__), "..", meal.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
    db.delete(meal)
    db.commit()
    return {"ok": True}
