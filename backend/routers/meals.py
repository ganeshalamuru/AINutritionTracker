import asyncio
import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session
from database import get_db
from models import Meal, Macros, Micros, AppConfig
from schemas import (
    AnalyzeResponse, MealItem, MealLogRequest, MealLogResponse, LogGroupRequest,
    MealPatch, MealDetail, MealSummary, MealSubSummary, MealGroupSummary,
    TimelineResponse, MacrosData, MicrosData
)
from services.gemini_service import analyze_meal_image, DEFAULT_MODEL, DEFAULT_PROVIDER
from services.nutrition_db import nutrients_for_items, UsdaRateLimitError

router = APIRouter(prefix="/meals", tags=["meals"])

UPLOADS_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")


def _config_value(db: Session, key: str, default: str) -> str:
    config = db.query(AppConfig).filter(AppConfig.key == key).first()
    return config.value if config and config.value else default


def get_api_key(db: Session, provider: str = "gemini") -> str:
    key_name = "groq_api_key" if provider == "groq" else "gemini_api_key"
    label = "Groq" if provider == "groq" else "Gemini"
    value = _config_value(db, key_name, "")
    if not value:
        raise HTTPException(
            status_code=503,
            detail=f"{label} API key not configured. Go to Settings to add your key."
        )
    return value


def get_vision_config(db: Session) -> tuple[str, str]:
    """Returns (provider, model) for vision analysis, falling back to defaults."""
    provider = _config_value(db, "vision_provider", DEFAULT_PROVIDER)
    model = _config_value(db, "vision_model", DEFAULT_MODEL)
    return provider, model


def _macros_data(macros) -> MacrosData:
    if not macros:
        return MacrosData()
    return MacrosData(
        calories=macros.calories or 0,
        protein_g=macros.protein_g or 0,
        carbs_g=macros.carbs_g or 0,
        fat_g=macros.fat_g or 0,
        fiber_g=macros.fiber_g or 0,
        sugar_g=macros.sugar_g or 0,
        sodium_mg=macros.sodium_mg or 0,
    )


def _micros_data(micros) -> MicrosData:
    if not micros:
        return MicrosData()
    return MicrosData(**{
        c.name: getattr(micros, c.name) or 0
        for c in Micros.__table__.columns if c.name not in ("id", "meal_id")
    })


def _sum_micros(a: MicrosData, b: MicrosData) -> MicrosData:
    return MicrosData(**{
        field: getattr(a, field) + getattr(b, field)
        for field in MicrosData.model_fields
    })


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_meal(
    image: UploadFile = File(...),
    profile_id: int = Form(default=0),
    user_note: Optional[str] = Form(default=None),
    db: Session = Depends(get_db)
):
    provider, model = get_vision_config(db)
    api_key = get_api_key(db, provider)

    image_bytes = await image.read()
    token = str(uuid.uuid4())
    temp_path = os.path.join(UPLOADS_DIR, f"{token}.jpg")
    with open(temp_path, "wb") as f:
        f.write(image_bytes)

    try:
        result = await asyncio.to_thread(
            analyze_meal_image, image_bytes, api_key, user_note or "", model, provider
        )
    except Exception as e:
        os.remove(temp_path)
        # The vision service already logs this error (timestamped). Map it to HTTP here.
        err = str(e).lower()
        raw = str(e)
        if "429" in err or "rate" in err or "per_minute" in err or "requests_per_minute" in err:
            raise HTTPException(status_code=429, detail=f"Rate limit hit — wait 60 seconds and try again. ({raw})")
        if "quota" in err or "daily" in err or "resource_exhausted" in err or "per_day" in err:
            raise HTTPException(status_code=429, detail=f"Daily quota exhausted — resets on the provider's reset schedule. ({raw})")
        if "timeout" in err or "timed out" in err or "deadline" in err or "504" in err:
            raise HTTPException(status_code=504, detail=f"AI analysis timed out — the model didn't respond. Try again. ({raw})")
        raise HTTPException(status_code=502, detail=f"AI analysis failed: {raw}")

    # Stage 2: turn the model's ingredient list into real nutrient numbers via the
    # USDA food database (the model no longer estimates macros/micros itself).
    items = result.get("items", [])
    usda_key = _config_value(db, "usda_api_key", "DEMO_KEY")
    try:
        macros_d, micros_d, unmatched, skipped = await asyncio.to_thread(
            nutrients_for_items, items, usda_key
        )
    except UsdaRateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail="USDA rate limit reached — add your free FoodData Central key in "
                   "Settings → USDA Food Database Key. "
                   f"({e})",
        )

    macros = MacrosData(**macros_d)
    micros = MicrosData(**micros_d)

    return AnalyzeResponse(
        meal_name=result.get("meal_name", "Unknown meal"),
        meal_type=result.get("meal_type", "snack"),
        confidence=result.get("confidence", "medium"),
        estimated_serving=result.get("estimated_serving"),
        macros=macros,
        micros=micros,
        items=[MealItem(food=i.get("food", ""), grams=i.get("grams") or 0) for i in items],
        unmatched=unmatched,
        skipped=skipped,
        temp_image_token=token,
        notes=result.get("notes"),
    )


def _create_meal_record(db: Session, data: MealLogRequest, group_id: Optional[str] = None) -> Meal:
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
        group_id=group_id,
    )
    db.add(meal)
    db.flush()

    db.add(Macros(meal_id=meal.id, **data.macros.model_dump()))
    db.add(Micros(meal_id=meal.id, **data.micros.model_dump()))
    return meal


def _cleanup_temp(data: MealLogRequest):
    if data.temp_image_token and not data.keep_image:
        temp_path = os.path.join(UPLOADS_DIR, f"{data.temp_image_token}.jpg")
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/log", response_model=MealLogResponse)
def log_meal(data: MealLogRequest, db: Session = Depends(get_db)):
    if data.profile_id == 0:
        raise HTTPException(status_code=400, detail="Guest cannot log meals")
    meal = _create_meal_record(db, data)
    db.commit()
    _cleanup_temp(data)
    db.refresh(meal)
    return MealLogResponse(id=meal.id, logged_at=meal.logged_at)


@router.post("/log-group")
def log_group(data: LogGroupRequest, db: Session = Depends(get_db)):
    if not data.meals:
        raise HTTPException(status_code=400, detail="No meals provided")
    for m in data.meals:
        if m.profile_id == 0:
            raise HTTPException(status_code=400, detail="Guest cannot log meals")

    meal_ids = []
    for meal_data in data.meals:
        meal = _create_meal_record(db, meal_data, group_id=data.group_id)
        meal_ids.append(meal.id)

    db.commit()

    for meal_data in data.meals:
        _cleanup_temp(meal_data)

    return {"group_id": data.group_id, "meal_ids": meal_ids}


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
    group_index = {}

    for m in meals:
        md = _macros_data(m.macros)
        mic = _micros_data(m.micros)

        if m.group_id:
            if m.group_id in group_index:
                group = items[group_index[m.group_id]]
                group.sub_meals.append(MealSubSummary(
                    id=m.id, meal_name=m.meal_name, meal_type=m.meal_type,
                    logged_at=m.logged_at, macros=md,
                ))
                t = group.total_macros
                group.total_macros = MacrosData(
                    calories=t.calories + md.calories,
                    protein_g=t.protein_g + md.protein_g,
                    carbs_g=t.carbs_g + md.carbs_g,
                    fat_g=t.fat_g + md.fat_g,
                    fiber_g=t.fiber_g + md.fiber_g,
                    sugar_g=t.sugar_g + md.sugar_g,
                    sodium_mg=t.sodium_mg + md.sodium_mg,
                )
                group.total_micros = _sum_micros(group.total_micros, mic)
            else:
                group = MealGroupSummary(
                    group_id=m.group_id,
                    logged_at=m.logged_at,
                    sub_meals=[MealSubSummary(
                        id=m.id, meal_name=m.meal_name, meal_type=m.meal_type,
                        logged_at=m.logged_at, macros=md,
                    )],
                    total_macros=md,
                    total_micros=mic,
                )
                group_index[m.group_id] = len(items)
                items.append(group)
        else:
            items.append(MealSummary(
                id=m.id,
                meal_name=m.meal_name,
                meal_type=m.meal_type,
                logged_at=m.logged_at,
                calories=md.calories,
                protein_g=md.protein_g,
                carbs_g=md.carbs_g,
                fat_g=md.fat_g,
                fiber_g=md.fiber_g,
                sugar_g=md.sugar_g,
                sodium_mg=md.sodium_mg,
                has_image=m.image_path is not None,
                group_id=None,
            ))

    return TimelineResponse(items=items, total=total, page=page, limit=limit)


@router.get("/group/{group_id}", response_model=MealGroupSummary)
def get_group(group_id: str, db: Session = Depends(get_db)):
    meals = db.query(Meal).filter(Meal.group_id == group_id).order_by(Meal.logged_at).all()
    if not meals:
        raise HTTPException(status_code=404, detail="Group not found")
    sub_meals = []
    total_macros = MacrosData()
    total_micros = MicrosData()
    for m in meals:
        md = _macros_data(m.macros)
        mic = _micros_data(m.micros)
        sub_meals.append(MealSubSummary(id=m.id, meal_name=m.meal_name, meal_type=m.meal_type, logged_at=m.logged_at, macros=md))
        total_macros = MacrosData(
            calories=total_macros.calories + md.calories,
            protein_g=total_macros.protein_g + md.protein_g,
            carbs_g=total_macros.carbs_g + md.carbs_g,
            fat_g=total_macros.fat_g + md.fat_g,
            fiber_g=total_macros.fiber_g + md.fiber_g,
            sugar_g=total_macros.sugar_g + md.sugar_g,
            sodium_mg=total_macros.sodium_mg + md.sodium_mg,
        )
        total_micros = _sum_micros(total_micros, mic)
    return MealGroupSummary(
        group_id=group_id,
        logged_at=meals[0].logged_at,
        sub_meals=sub_meals,
        total_macros=total_macros,
        total_micros=total_micros,
    )


@router.delete("/group/{group_id}")
def delete_group(group_id: str, db: Session = Depends(get_db)):
    meals = db.query(Meal).filter(Meal.group_id == group_id).all()
    if not meals:
        raise HTTPException(status_code=404, detail="Group not found")
    for meal in meals:
        if meal.image_path:
            full_path = os.path.join(os.path.dirname(__file__), "..", meal.image_path)
            if os.path.exists(full_path):
                os.remove(full_path)
        db.delete(meal)
    db.commit()
    return {"ok": True}


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
