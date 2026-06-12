from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import extract
from database import get_db
from models import Meal, Macros, Micros
from schemas import DailySummary, MonthlySummary, DailyBreakdown, MealSummary

router = APIRouter(prefix="/nutrition", tags=["nutrition"])

MACRO_FIELDS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]
MICRO_FIELDS = [
    "vitamin_a_mcg", "vitamin_d_mcg", "vitamin_e_mg", "vitamin_k_mcg", "vitamin_c_mg",
    "vitamin_b1_mg", "vitamin_b2_mg", "vitamin_b3_mg", "vitamin_b6_mg", "vitamin_b12_mcg",
    "folate_mcg", "calcium_mg", "iron_mg", "magnesium_mg", "potassium_mg", "zinc_mg", "phosphorus_mg"
]


def _meal_to_summary(m: Meal) -> MealSummary:
    macros = m.macros
    return MealSummary(
        id=m.id,
        meal_name=m.meal_name,
        meal_type=m.meal_type,
        logged_at=m.logged_at,
        calories=macros.calories if macros else 0,
        protein_g=macros.protein_g if macros else 0,
        carbs_g=macros.carbs_g if macros else 0,
        fat_g=macros.fat_g if macros else 0,
        fiber_g=macros.fiber_g if macros else 0,
        sugar_g=macros.sugar_g if macros else 0,
        sodium_mg=macros.sodium_mg if macros else 0,
        has_image=m.image_path is not None,
        group_id=m.group_id,
    )


@router.get("/daily", response_model=DailySummary)
def daily_summary(profile_id: int, date_from: Optional[str] = None, date_to: Optional[str] = None, db: Session = Depends(get_db)):
    if not date_from:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        date_from = today + "T00:00:00"
        date_to = today + "T23:59:59.999999"

    meals = (
        db.query(Meal)
        .filter(
            Meal.profile_id == profile_id,
            Meal.logged_at >= date_from,
            Meal.logged_at < date_to,
        )
        .order_by(Meal.logged_at.desc())
        .all()
    )

    totals: dict = {f: 0.0 for f in MACRO_FIELDS + MICRO_FIELDS}
    for m in meals:
        if m.macros:
            for f in MACRO_FIELDS:
                totals[f] += getattr(m.macros, f) or 0
        if m.micros:
            for f in MICRO_FIELDS:
                totals[f] += getattr(m.micros, f) or 0

    return DailySummary(
        date=date_from[:10],
        meal_count=len(meals),
        totals=totals,
        meals=[_meal_to_summary(m) for m in meals],
    )


@router.get("/monthly", response_model=MonthlySummary)
def monthly_summary(profile_id: int, year: int, month: int, db: Session = Depends(get_db)):
    meals = (
        db.query(Meal)
        .filter(
            Meal.profile_id == profile_id,
            extract("year", Meal.logged_at) == year,
            extract("month", Meal.logged_at) == month,
        )
        .order_by(Meal.logged_at)
        .all()
    )

    by_date: dict[str, dict] = {}
    for m in meals:
        d = m.logged_at.strftime("%Y-%m-%d")
        if d not in by_date:
            by_date[d] = {f: 0.0 for f in MACRO_FIELDS + MICRO_FIELDS}
        if m.macros:
            for f in MACRO_FIELDS:
                by_date[d][f] += getattr(m.macros, f) or 0
        if m.micros:
            for f in MICRO_FIELDS:
                by_date[d][f] += getattr(m.micros, f) or 0

    daily_breakdown = [
        DailyBreakdown(
            date=d,
            calories=v["calories"],
            protein_g=v["protein_g"],
            carbs_g=v["carbs_g"],
            fat_g=v["fat_g"],
        )
        for d, v in sorted(by_date.items())
    ]

    days_logged = len(by_date)
    monthly_totals: dict = {f: 0.0 for f in MACRO_FIELDS + MICRO_FIELDS}
    for v in by_date.values():
        for f in MACRO_FIELDS + MICRO_FIELDS:
            monthly_totals[f] += v[f]

    monthly_averages = {
        f: round(monthly_totals[f] / days_logged, 1) if days_logged else 0
        for f in MACRO_FIELDS + MICRO_FIELDS
    }

    return MonthlySummary(
        year=year,
        month=month,
        daily_breakdown=daily_breakdown,
        monthly_averages=monthly_averages,
        monthly_totals=monthly_totals,
        days_logged=days_logged,
    )
