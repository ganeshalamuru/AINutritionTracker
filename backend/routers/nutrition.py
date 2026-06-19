"""Nutrition summary routes — thin wrappers over services.summary_service. Scoped to the
authenticated user (core.auth.get_current_user); no client-supplied user id."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from models import User
from schemas import DailySummary, MonthlySummary
from services import summary_service

router = APIRouter(prefix="/nutrition", tags=["nutrition"])


@router.get("/daily", response_model=DailySummary, summary="Daily nutrition totals")
def daily_summary(
    date_from: str | None = None,
    date_to: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return summary_service.daily_summary(db, user.id, date_from, date_to)


@router.get("/monthly", response_model=MonthlySummary, summary="Monthly nutrition breakdown")
def monthly_summary(
    year: int,
    month: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return summary_service.monthly_summary(db, user.id, year, month)
