"""Nutrition summary routes — thin wrappers over services.summary_service."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.database import get_db
from schemas import DailySummary, MonthlySummary
from services import summary_service

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@router.get("/daily", response_model=DailySummary, summary="Daily nutrition totals")
def daily_summary(
    profile_id: int,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
):
    return summary_service.daily_summary(db, profile_id, date_from, date_to)


@router.get("/monthly", response_model=MonthlySummary, summary="Monthly nutrition breakdown")
def monthly_summary(profile_id: int, year: int, month: int, db: Session = Depends(get_db)):
    return summary_service.monthly_summary(db, profile_id, year, month)
