"""Meal HTTP routes — thin wrappers over services.meal_service. The route ORDER
matters: the static `/group/...` and `/timeline` paths must be declared before the
`/{meal_id}` catch-all or FastAPI would match e.g. "timeline" as a meal id."""

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.orm import Session

from core.database import get_db
from schemas import (
    AnalyzeResponse,
    LogGroupRequest,
    LogGroupResponse,
    MealDetail,
    MealGroupSummary,
    MealLogRequest,
    MealLogResponse,
    MealPatch,
    OkResponse,
    TimelineResponse,
)
from services import meal_service

router = APIRouter(prefix="/meals", tags=["meals"])


@router.post("/analyze", response_model=AnalyzeResponse, summary="Analyze a meal photo")
async def analyze_meal(
    image: UploadFile = File(...),
    profile_id: int = Form(default=0),
    user_note: str | None = Form(default=None),
    db: Session = Depends(get_db),
):
    image_bytes = await image.read()
    return await meal_service.analyze_image(db, image_bytes, user_note)


@router.post(
    "/log",
    response_model=MealLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a single analyzed meal",
)
def log_meal(data: MealLogRequest, db: Session = Depends(get_db)):
    return meal_service.log_meal(db, data)


@router.post(
    "/log-group",
    response_model=LogGroupResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Log a grouped multi-photo meal session",
)
def log_group(data: LogGroupRequest, db: Session = Depends(get_db)):
    return meal_service.log_group(db, data)


@router.get("/timeline", response_model=TimelineResponse, summary="Paginated meal timeline")
def get_timeline(
    profile_id: int,
    page: int = 1,
    limit: int = 20,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    return meal_service.build_timeline(db, profile_id, page, limit, date_from, date_to)


@router.get("/group/{group_id}", response_model=MealGroupSummary, summary="Get a meal group")
def get_group(group_id: str, db: Session = Depends(get_db)):
    return meal_service.get_group(db, group_id)


@router.delete("/group/{group_id}", response_model=OkResponse, summary="Delete a meal group")
def delete_group(group_id: str, db: Session = Depends(get_db)):
    return meal_service.delete_group(db, group_id)


@router.get("/{meal_id}", response_model=MealDetail, summary="Get meal detail")
def get_meal(meal_id: int, db: Session = Depends(get_db)):
    return meal_service.get_meal(db, meal_id)


@router.patch("/{meal_id}", response_model=OkResponse, summary="Update a meal")
def patch_meal(meal_id: int, data: MealPatch, db: Session = Depends(get_db)):
    return meal_service.patch_meal(db, meal_id, data)


@router.delete("/{meal_id}", response_model=OkResponse, summary="Delete a meal")
def delete_meal(meal_id: int, db: Session = Depends(get_db)):
    return meal_service.delete_meal(db, meal_id)
