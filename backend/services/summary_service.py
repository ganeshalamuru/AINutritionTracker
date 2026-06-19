"""Aggregation logic for the nutrition summaries (daily totals + monthly breakdown).
Routers call these and return the result directly.
"""

from datetime import UTC, datetime

from sqlalchemy import extract
from sqlalchemy.orm import Session

from core.nutrients import NUTRIENT_KEYS, to_nutrients_data
from models import Meal
from schemas import DailyBreakdown, DailySummary, MealSummary, MonthlySummary

_ALL_FIELDS = NUTRIENT_KEYS


def _meal_to_summary(m: Meal) -> MealSummary:
    nd = to_nutrients_data(m.nutrients)
    return MealSummary(
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
        group_id=m.group_id,
    )


def _accumulate(target: dict, m: Meal):
    """Add a meal's nutrient values into a running totals dict."""
    if m.nutrients:
        for f in NUTRIENT_KEYS:
            target[f] += getattr(m.nutrients, f) or 0


def daily_summary(
    db: Session, user_id: int, date_from: str | None, date_to: str | None
) -> DailySummary:
    if not date_from:
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        date_from = today + "T00:00:00"
        date_to = today + "T23:59:59.999999"

    meals = (
        db.query(Meal)
        .filter(
            Meal.profile_id == user_id,
            Meal.logged_at >= date_from,
            Meal.logged_at < date_to,
        )
        .order_by(Meal.logged_at.desc())
        .all()
    )

    totals = {f: 0.0 for f in _ALL_FIELDS}
    for m in meals:
        _accumulate(totals, m)

    return DailySummary(
        date=date_from[:10],
        meal_count=len(meals),
        totals=totals,
        meals=[_meal_to_summary(m) for m in meals],
    )


def monthly_summary(db: Session, user_id: int, year: int, month: int) -> MonthlySummary:
    meals = (
        db.query(Meal)
        .filter(
            Meal.profile_id == user_id,
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
            by_date[d] = {f: 0.0 for f in _ALL_FIELDS}
        _accumulate(by_date[d], m)

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
    monthly_totals = {f: 0.0 for f in _ALL_FIELDS}
    for v in by_date.values():
        for f in _ALL_FIELDS:
            monthly_totals[f] += v[f]

    monthly_averages = {
        f: round(monthly_totals[f] / days_logged, 1) if days_logged else 0 for f in _ALL_FIELDS
    }

    return MonthlySummary(
        year=year,
        month=month,
        daily_breakdown=daily_breakdown,
        monthly_averages=monthly_averages,
        monthly_totals=monthly_totals,
        days_logged=days_logged,
    )
