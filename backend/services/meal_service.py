"""Business logic for meals: the two-stage analyze orchestration, logging single and
grouped meals, and the timeline/group/detail read models. Routers call into here and
stay thin — they only parse the request and return what these functions build.
"""
import asyncio
import os
import uuid
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core import config
from core.config import UPLOADS_DIR, BACKEND_DIR
from core.nutrients import to_macros_data, to_micros_data, sum_macros, sum_micros
from models import Meal, Macros, Micros
from schemas import (
    AnalyzeResponse, DishBreakdown, IngredientBreakdown, MealLogRequest, MealLogResponse,
    LogGroupRequest, MealPatch, MealDetail, MealSummary, MealSubSummary, MealGroupSummary,
    TimelineResponse, MacrosData, MicrosData,
)
from services.vision_service import analyze_meal_image
from services.usda_service import nutrients_for_meal, UsdaRateLimitError


# --- analyze (Stage 1 perception + Stage 2 nutrient lookup) ---

def _map_vision_error(e: Exception) -> HTTPException:
    """Translate a vision-provider failure into an HTTP error. The vision service has
    already logged the error (timestamped); here we only choose the status + message."""
    err = str(e).lower()
    raw = str(e)
    if "429" in err or "rate" in err or "per_minute" in err or "requests_per_minute" in err:
        return HTTPException(status_code=429, detail=f"Rate limit hit — wait 60 seconds and try again. ({raw})")
    if "quota" in err or "daily" in err or "resource_exhausted" in err or "per_day" in err:
        return HTTPException(status_code=429, detail=f"Daily quota exhausted — resets on the provider's reset schedule. ({raw})")
    if "timeout" in err or "timed out" in err or "deadline" in err or "504" in err:
        return HTTPException(status_code=504, detail=f"AI analysis timed out — the model didn't respond. Try again. ({raw})")
    return HTTPException(status_code=502, detail=f"AI analysis failed: {raw}")


async def analyze_image(db: Session, image_bytes: bytes, user_note: Optional[str]) -> AnalyzeResponse:
    provider, model = config.get_vision_config(db)
    # Guard only: raises 503 "set your key" if the provider's key isn't configured. The
    # vision client itself is built once at startup / on config change (vision_service),
    # so the key no longer flows into the call.
    config.get_api_key(db, provider)

    token = str(uuid.uuid4())
    temp_path = os.path.join(UPLOADS_DIR, f"{token}.jpg")
    with open(temp_path, "wb") as f:
        f.write(image_bytes)

    # Stage 1: vision model identifies each dish + its base-ingredient fallback (no nutrients).
    try:
        result = await asyncio.to_thread(
            analyze_meal_image, image_bytes, user_note or "", model, provider
        )
    except Exception as e:
        os.remove(temp_path)
        raise _map_vision_error(e)

    # Stage 2: turn the dish list into real nutrient numbers via the USDA food database
    # (dish-first, decomposing into base ingredients only when a dish has no match).
    dishes = result.get("dishes", [])
    usda_key = config.get_usda_key(db)
    try:
        macros_d, micros_d, unmatched, skipped, breakdown = await asyncio.to_thread(
            nutrients_for_meal, dishes, usda_key
        )
    except UsdaRateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail="USDA rate limit reached — add your free FoodData Central key in "
                   "Settings → USDA Food Database Key. "
                   f"({e})",
        )

    return AnalyzeResponse(
        meal_name=result.get("meal_name", "Unknown meal"),
        meal_type=result.get("meal_type", "snack"),
        confidence=result.get("confidence", "medium"),
        estimated_serving=result.get("estimated_serving"),
        macros=MacrosData(**macros_d),
        micros=MicrosData(**micros_d),
        dishes=[DishBreakdown(
            name=d.get("name", ""),
            grams=d.get("grams") or 0,
            matched=d.get("matched", False),
            macros=MacrosData(**d.get("macros", {})),
            micros=MicrosData(**d.get("micros", {})),
            ingredients=[IngredientBreakdown(**i) for i in d.get("ingredients", [])],
        ) for d in breakdown],
        unmatched=unmatched,
        skipped=skipped,
        temp_image_token=token,
        notes=result.get("notes"),
    )


# --- logging meals ---

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


def log_meal(db: Session, data: MealLogRequest) -> MealLogResponse:
    if data.profile_id == 0:
        raise HTTPException(status_code=400, detail="Guest cannot log meals")
    meal = _create_meal_record(db, data)
    db.commit()
    _cleanup_temp(data)
    db.refresh(meal)
    return MealLogResponse(id=meal.id, logged_at=meal.logged_at)


def log_group(db: Session, data: LogGroupRequest) -> dict:
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


# --- read models ---

def build_timeline(db: Session, profile_id: int, page: int, limit: int,
                   date_from: Optional[str], date_to: Optional[str]) -> TimelineResponse:
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

    items: list = []
    group_index: dict[str, int] = {}

    for m in meals:
        md = to_macros_data(m.macros)
        mic = to_micros_data(m.micros)

        if m.group_id:
            if m.group_id in group_index:
                group = items[group_index[m.group_id]]
                group.sub_meals.append(MealSubSummary(
                    id=m.id, meal_name=m.meal_name, meal_type=m.meal_type,
                    logged_at=m.logged_at, macros=md,
                ))
                group.total_macros = sum_macros(group.total_macros, md)
                group.total_micros = sum_micros(group.total_micros, mic)
            else:
                group_index[m.group_id] = len(items)
                items.append(MealGroupSummary(
                    group_id=m.group_id,
                    logged_at=m.logged_at,
                    sub_meals=[MealSubSummary(
                        id=m.id, meal_name=m.meal_name, meal_type=m.meal_type,
                        logged_at=m.logged_at, macros=md,
                    )],
                    total_macros=md,
                    total_micros=mic,
                ))
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


def get_group(db: Session, group_id: str) -> MealGroupSummary:
    meals = db.query(Meal).filter(Meal.group_id == group_id).order_by(Meal.logged_at).all()
    if not meals:
        raise HTTPException(status_code=404, detail="Group not found")
    sub_meals = []
    total_macros = MacrosData()
    total_micros = MicrosData()
    for m in meals:
        md = to_macros_data(m.macros)
        mic = to_micros_data(m.micros)
        sub_meals.append(MealSubSummary(
            id=m.id, meal_name=m.meal_name, meal_type=m.meal_type, logged_at=m.logged_at, macros=md))
        total_macros = sum_macros(total_macros, md)
        total_micros = sum_micros(total_micros, mic)
    return MealGroupSummary(
        group_id=group_id,
        logged_at=meals[0].logged_at,
        sub_meals=sub_meals,
        total_macros=total_macros,
        total_micros=total_micros,
    )


def delete_group(db: Session, group_id: str) -> dict:
    meals = db.query(Meal).filter(Meal.group_id == group_id).all()
    if not meals:
        raise HTTPException(status_code=404, detail="Group not found")
    for meal in meals:
        _remove_image_file(meal)
        db.delete(meal)
    db.commit()
    return {"ok": True}


def get_meal(db: Session, meal_id: int) -> MealDetail:
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    return MealDetail(
        id=meal.id,
        meal_name=meal.meal_name,
        meal_type=meal.meal_type,
        logged_at=meal.logged_at,
        notes=meal.notes,
        has_image=meal.image_path is not None,
        macros=to_macros_data(meal.macros),
        micros=to_micros_data(meal.micros),
    )


def patch_meal(db: Session, meal_id: int, data: MealPatch) -> dict:
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


def delete_meal(db: Session, meal_id: int) -> dict:
    meal = db.query(Meal).filter(Meal.id == meal_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    _remove_image_file(meal)
    db.delete(meal)
    db.commit()
    return {"ok": True}


def _remove_image_file(meal: Meal):
    if meal.image_path:
        full_path = os.path.join(BACKEND_DIR, meal.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
