"""Business logic for meals: the two-stage analyze orchestration, logging single and
grouped meals, and the timeline/group/detail read models. Routers call into here and
stay thin — they only parse the request and return what these functions build.
"""

import asyncio
import os
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core import config
from core.config import BACKEND_DIR, UPLOADS_DIR
from core.nutrients import sum_nutrients, to_nutrients_data
from models import Meal, Nutrients
from schemas import (
    AnalyzeResponse,
    DishBreakdown,
    IngredientBreakdown,
    LogGroupRequest,
    MealDetail,
    MealGroupSummary,
    MealLogRequest,
    MealLogResponse,
    MealPatch,
    MealSubSummary,
    MealSummary,
    NutrientsData,
    TimelineResponse,
)
from services.usda_service import UsdaRateLimitError, nutrients_for_meal
from services.vision_service import analyze_meal_image

# --- analyze (Stage 1 perception + Stage 2 nutrient lookup) ---


def _write_temp(path: str, data: bytes) -> None:
    """Blocking write of the uploaded image to a temp path. Run off-thread by callers on
    the async path so the event loop isn't blocked on disk I/O."""
    with open(path, "wb") as f:
        f.write(data)


def _remove_temp(path: str) -> None:
    """Best-effort temp-file removal: skip if it's already gone so cleanup never masks the
    error that triggered it (or, on the success path, a benign double-delete)."""
    if os.path.exists(path):
        os.remove(path)


def _map_vision_error(e: Exception) -> HTTPException:
    """Translate a vision-provider failure into an HTTP error. The vision service has
    already logged the error (timestamped); here we only choose the status + message."""
    err = str(e).lower()
    raw = str(e)
    if "429" in err or "rate" in err or "per_minute" in err or "requests_per_minute" in err:
        return HTTPException(
            status_code=429, detail=f"Rate limit hit — wait 60 seconds and try again. ({raw})"
        )
    if "quota" in err or "daily" in err or "resource_exhausted" in err or "per_day" in err:
        return HTTPException(
            status_code=429,
            detail=f"Daily quota exhausted — resets on the provider's reset schedule. ({raw})",
        )
    if "timeout" in err or "timed out" in err or "deadline" in err or "504" in err:
        return HTTPException(
            status_code=504,
            detail=f"AI analysis timed out — the model didn't respond. Try again. ({raw})",
        )
    return HTTPException(status_code=502, detail=f"AI analysis failed: {raw}")


async def analyze_image(db: Session, image_bytes: bytes, user_note: str | None) -> AnalyzeResponse:
    provider, model = config.get_vision_config(db)
    # Guard only: raises 503 "set your key" if the provider's key isn't configured. The
    # vision client itself is built once at startup / on config change (vision_service),
    # so the key no longer flows into the call.
    config.get_api_key(db, provider)

    token = str(uuid.uuid4())
    temp_path = os.path.join(UPLOADS_DIR, f"{token}.jpg")
    # Offload the blocking disk write off the event loop, like the Stage-1/2 calls below.
    await asyncio.to_thread(_write_temp, temp_path, image_bytes)

    # Stage 1: vision model identifies each dish + its base-ingredient fallback (no nutrients).
    try:
        result = await asyncio.to_thread(
            analyze_meal_image, image_bytes, user_note or "", model, provider
        )
    except Exception as e:
        # Guard cleanup so a missing temp file can't mask the original vision error.
        _remove_temp(temp_path)
        raise _map_vision_error(e) from e

    # Stage 2: turn the dish list into real nutrient numbers via the USDA food database
    # (dish-first, decomposing into base ingredients only when a dish has no match).
    dishes = result.get("dishes", [])
    try:
        nutrients_d, unmatched, skipped, breakdown = await asyncio.to_thread(
            nutrients_for_meal, dishes
        )
    except UsdaRateLimitError as e:
        raise HTTPException(
            status_code=429,
            detail="USDA rate limit reached — add your free FoodData Central key in "
            "Settings → USDA Food Database Key. "
            f"({e})",
        ) from e

    return AnalyzeResponse(
        meal_name=result.get("meal_name", "Unknown meal"),
        meal_type=result.get("meal_type", "snack"),
        confidence=result.get("confidence", "medium"),
        estimated_serving=result.get("estimated_serving"),
        nutrients=NutrientsData(**nutrients_d),
        dishes=[
            DishBreakdown(
                name=d.get("name", ""),
                grams=d.get("grams") or 0,
                matched=d.get("matched", False),
                nutrients=NutrientsData(**d.get("nutrients", {})),
                ingredients=[IngredientBreakdown(**i) for i in d.get("ingredients", [])],
            )
            for d in breakdown
        ],
        unmatched=unmatched,
        skipped=skipped,
        temp_image_token=token,
        notes=result.get("notes"),
    )


# --- logging meals ---


def _create_meal_record(
    db: Session, data: MealLogRequest, user_id: int, group_id: str | None = None
) -> Meal:
    image_path = None
    if data.temp_image_token and data.keep_image:
        temp_path = os.path.join(UPLOADS_DIR, f"{data.temp_image_token}.jpg")
        if os.path.exists(temp_path):
            image_path = f"uploads/{data.temp_image_token}.jpg"

    # The owner is always the authenticated user — never a client-supplied id.
    meal = Meal(
        user_id=user_id,
        meal_name=data.meal_name,
        meal_type=data.meal_type,
        image_path=image_path,
        notes=data.notes,
        group_id=group_id,
    )
    db.add(meal)
    db.flush()

    db.add(Nutrients(meal_id=meal.id, **data.nutrients.model_dump()))
    return meal


def _cleanup_temp(data: MealLogRequest):
    if data.temp_image_token and not data.keep_image:
        _remove_temp(os.path.join(UPLOADS_DIR, f"{data.temp_image_token}.jpg"))


def log_meal(db: Session, data: MealLogRequest, user_id: int) -> MealLogResponse:
    meal = _create_meal_record(db, data, user_id)
    db.commit()
    _cleanup_temp(data)
    db.refresh(meal)
    return MealLogResponse(id=meal.id, logged_at=meal.logged_at)


def log_group(db: Session, data: LogGroupRequest, user_id: int) -> dict:
    if not data.meals:
        raise HTTPException(status_code=400, detail="No meals provided")

    meal_ids = []
    for meal_data in data.meals:
        meal = _create_meal_record(db, meal_data, user_id, group_id=data.group_id)
        meal_ids.append(meal.id)
    db.commit()

    for meal_data in data.meals:
        _cleanup_temp(meal_data)
    return {"group_id": data.group_id, "meal_ids": meal_ids}


# --- read models ---


def build_timeline(
    db: Session, user_id: int, page: int, limit: int, date_from: str | None, date_to: str | None
) -> TimelineResponse:
    query = db.query(Meal).filter(Meal.user_id == user_id).order_by(Meal.logged_at.desc())
    if date_from:
        query = query.filter(Meal.logged_at >= date_from)
    if date_to:
        query = query.filter(Meal.logged_at <= date_to)

    total = query.count()
    meals = query.offset((page - 1) * limit).limit(limit).all()

    items: list = []
    group_index: dict[str, int] = {}

    for m in meals:
        nd = to_nutrients_data(m.nutrients)

        if m.group_id:
            if m.group_id in group_index:
                group = items[group_index[m.group_id]]
                group.sub_meals.append(
                    MealSubSummary(
                        id=m.id,
                        meal_name=m.meal_name,
                        meal_type=m.meal_type,
                        logged_at=m.logged_at,
                        nutrients=nd,
                    )
                )
                group.total_nutrients = sum_nutrients(group.total_nutrients, nd)
            else:
                group_index[m.group_id] = len(items)
                items.append(
                    MealGroupSummary(
                        group_id=m.group_id,
                        logged_at=m.logged_at,
                        sub_meals=[
                            MealSubSummary(
                                id=m.id,
                                meal_name=m.meal_name,
                                meal_type=m.meal_type,
                                logged_at=m.logged_at,
                                nutrients=nd,
                            )
                        ],
                        total_nutrients=nd,
                    )
                )
        else:
            items.append(
                MealSummary(
                    id=m.id,
                    meal_name=m.meal_name,
                    meal_type=m.meal_type,
                    logged_at=m.logged_at,
                    calories=nd.calories,
                    protein_g=nd.protein_g,
                    carbs_g=nd.carbs_g,
                    fat_g=nd.fat_g,
                    fiber_g=nd.fiber_g,
                    sugar_g=nd.sugar_g,
                    sodium_mg=nd.sodium_mg,
                    has_image=m.image_path is not None,
                    group_id=None,
                )
            )

    return TimelineResponse(items=items, total=total, page=page, limit=limit)


def get_group(db: Session, group_id: str, user_id: int) -> MealGroupSummary:
    meals = (
        db.query(Meal)
        .filter(Meal.group_id == group_id, Meal.user_id == user_id)
        .order_by(Meal.logged_at)
        .all()
    )
    if not meals:
        raise HTTPException(status_code=404, detail="Group not found")
    sub_meals = []
    total_nutrients = NutrientsData()
    for m in meals:
        nd = to_nutrients_data(m.nutrients)
        sub_meals.append(
            MealSubSummary(
                id=m.id,
                meal_name=m.meal_name,
                meal_type=m.meal_type,
                logged_at=m.logged_at,
                nutrients=nd,
            )
        )
        total_nutrients = sum_nutrients(total_nutrients, nd)
    return MealGroupSummary(
        group_id=group_id,
        logged_at=meals[0].logged_at,
        sub_meals=sub_meals,
        total_nutrients=total_nutrients,
    )


def delete_group(db: Session, group_id: str, user_id: int) -> dict:
    meals = db.query(Meal).filter(Meal.group_id == group_id, Meal.user_id == user_id).all()
    if not meals:
        raise HTTPException(status_code=404, detail="Group not found")
    for meal in meals:
        _remove_image_file(meal)
        db.delete(meal)
    db.commit()
    return {"ok": True}


def get_meal(db: Session, meal_id: int, user_id: int) -> MealDetail:
    meal = _owned_meal(db, meal_id, user_id)
    return MealDetail(
        id=meal.id,
        meal_name=meal.meal_name,
        meal_type=meal.meal_type,
        logged_at=meal.logged_at,
        notes=meal.notes,
        has_image=meal.image_path is not None,
        nutrients=to_nutrients_data(meal.nutrients),
    )


def patch_meal(db: Session, meal_id: int, data: MealPatch, user_id: int) -> dict:
    meal = _owned_meal(db, meal_id, user_id)
    if data.meal_name is not None:
        meal.meal_name = data.meal_name
    if data.meal_type is not None:
        meal.meal_type = data.meal_type
    if data.notes is not None:
        meal.notes = data.notes
    db.commit()
    return {"ok": True}


def delete_meal(db: Session, meal_id: int, user_id: int) -> dict:
    meal = _owned_meal(db, meal_id, user_id)
    _remove_image_file(meal)
    db.delete(meal)
    db.commit()
    return {"ok": True}


def _owned_meal(db: Session, meal_id: int, user_id: int) -> Meal:
    """Fetch a meal that belongs to `user_id`, or 404. Filtering on the owner (rather than
    fetching then comparing) means another user's meal id is indistinguishable from a
    nonexistent one — no existence leak across accounts."""
    meal = db.query(Meal).filter(Meal.id == meal_id, Meal.user_id == user_id).first()
    if not meal:
        raise HTTPException(status_code=404, detail="Meal not found")
    return meal


def _remove_image_file(meal: Meal):
    if meal.image_path:
        full_path = os.path.join(BACKEND_DIR, meal.image_path)
        if os.path.exists(full_path):
            os.remove(full_path)
