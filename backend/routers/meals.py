"""Meal HTTP routes — thin wrappers over services.meal_service. The route ORDER
matters: the static `/group/...` and `/timeline` paths must be declared before the
`/{meal_id}` catch-all or FastAPI would match e.g. "timeline" as a meal id."""
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form
from sqlalchemy.orm import Session

from core.database import get_db
from schemas import (
    AnalyzeResponse, MealLogRequest, MealLogResponse, LogGroupRequest,
    MealPatch, MealDetail, MealGroupSummary, TimelineResponse,
)
from services import meal_service

router = APIRouter(prefix="/meals", tags=["meals"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_meal(
    image: UploadFile = File(...),
    profile_id: int = Form(default=0),
    user_note: Optional[str] = Form(default=None),
    db: Session = Depends(get_db),
):
    image_bytes = await image.read()
    return await meal_service.analyze_image(db, image_bytes, user_note)


@router.post("/log", response_model=MealLogResponse)
def log_meal(data: MealLogRequest, db: Session = Depends(get_db)):
    return meal_service.log_meal(db, data)


@router.post("/log-group")
def log_group(data: LogGroupRequest, db: Session = Depends(get_db)):
    return meal_service.log_group(db, data)


@router.get("/timeline", response_model=TimelineResponse)
def get_timeline(
    profile_id: int,
    page: int = 1,
    limit: int = 20,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return meal_service.build_timeline(db, profile_id, page, limit, date_from, date_to)


@router.get("/group/{group_id}", response_model=MealGroupSummary)
def get_group(group_id: str, db: Session = Depends(get_db)):
    return meal_service.get_group(db, group_id)


@router.delete("/group/{group_id}")
def delete_group(group_id: str, db: Session = Depends(get_db)):
    return meal_service.delete_group(db, group_id)


@router.get("/{meal_id}", response_model=MealDetail)
def get_meal(meal_id: int, db: Session = Depends(get_db)):
    return meal_service.get_meal(db, meal_id)


@router.patch("/{meal_id}")
def patch_meal(meal_id: int, data: MealPatch, db: Session = Depends(get_db)):
    return meal_service.patch_meal(db, meal_id, data)


@router.delete("/{meal_id}")
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    return meal_service.delete_meal(db, meal_id)
