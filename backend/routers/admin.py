"""Dev-only data-inspection API (mounted by main.py only when APP_ENV != production, the same
gate that controls /docs). Lets you browse both SQLite DBs — the app DB (nutrition.db) and the
offline USDA index (usda_local.db) — with structured views plus a guarded read-only SQL console.

Secrets never leak: app_config `*_api_key` values and profile PINs are redacted in every response
(including the raw SQL console — see services.admin_query.redact_rows)."""

import json
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from core.config import BACKEND_DIR
from core.database import get_db
from core.nutrients import to_nutrients_data
from models import AppConfig, Meal, Nutrients
from schemas import (
    AdminConfigEntry,
    AdminMeal,
    FoodCacheEntry,
    SqlQueryRequest,
    SqlQueryResult,
    TableInfo,
)
from services import admin_query, usda_local_search

router = APIRouter(prefix="/admin", tags=["admin"])

APP_DB_PATH = os.path.join(BACKEND_DIR, "nutrition.db")

# app_config keys whose values are secret and must be redacted everywhere.
SECRET_SUFFIX = "_api_key"


def _is_secret_key(key: str) -> bool:
    return key.endswith(SECRET_SUFFIX)


def _secret_values(db: Session) -> set[str]:
    """The configured API-key values (non-empty), for masking in raw SQL results."""
    rows = db.query(AppConfig).filter(AppConfig.key.like(f"%{SECRET_SUFFIX}")).all()
    return {r.value for r in rows if r.value}


@router.get("/tables", response_model=list[TableInfo], summary="List tables + row counts")
def list_tables(
    db_name: str = Query(default="app", alias="db", description="app | local"),
    db: Session = Depends(get_db),
):
    if db_name == "local":
        return [TableInfo(name=n, rows=c) for n, c in usda_local_search.table_counts().items()]
    if db_name == "app":
        names = [
            r[0]
            for r in db.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ).fetchall()
        ]
        out = []
        for name in names:
            count = db.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar()
            out.append(TableInfo(name=name, rows=count or 0))
        return out
    raise HTTPException(status_code=400, detail="db must be 'app' or 'local'")


@router.get(
    "/food-cache", response_model=list[FoodCacheEntry], summary="Browse the USDA lookup cache"
)
def food_cache(
    query: str | None = Query(default=None, description="Filter by cache key substring"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    sql = "SELECT query, fdc_id, nutrients_json, fetched_at FROM food_cache"
    params: dict = {}
    if query:
        sql += " WHERE query LIKE :q"
        params["q"] = f"%{query}%"
    sql += " ORDER BY fetched_at DESC LIMIT :lim OFFSET :off"
    params.update(lim=limit, off=offset)
    rows = db.execute(text(sql), params).fetchall()
    out = []
    for q, fdc_id, nutrients_json, fetched_at in rows:
        try:
            nutrients = json.loads(nutrients_json) if nutrients_json else {}
        except ValueError, TypeError:
            nutrients = {}
        out.append(
            FoodCacheEntry(query=q, fdc_id=fdc_id, nutrients=nutrients, fetched_at=fetched_at)
        )
    return out


@router.get("/meals", response_model=list[AdminMeal], summary="Browse logged meals")
def list_meals(
    profile_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    q = db.query(Meal)
    if profile_id is not None:
        q = q.filter(Meal.profile_id == profile_id)
    meals = q.order_by(Meal.logged_at.desc()).limit(limit).offset(offset).all()
    out = []
    for m in meals:
        nutrients = db.query(Nutrients).filter(Nutrients.meal_id == m.id).first()
        out.append(
            AdminMeal(
                id=m.id,
                profile_id=m.profile_id,
                meal_name=m.meal_name,
                meal_type=m.meal_type,
                logged_at=m.logged_at,
                nutrients=to_nutrients_data(nutrients),
            )
        )
    return out


@router.get(
    "/config", response_model=list[AdminConfigEntry], summary="App config (secrets redacted)"
)
def list_config(db: Session = Depends(get_db)):
    out = []
    for row in db.query(AppConfig).order_by(AppConfig.key).all():
        secret = _is_secret_key(row.key)
        # Secret rows show REDACTED when set, "" when unset — never the real key.
        value = (admin_query.REDACTED if row.value else "") if secret else row.value
        out.append(AdminConfigEntry(key=row.key, value=value, is_secret=secret))
    return out


@router.post("/query/{which}", response_model=SqlQueryResult, summary="Run a read-only SQL query")
def run_sql(which: str, body: SqlQueryRequest, db: Session = Depends(get_db)):
    """Execute one read-only SELECT against `app` (nutrition.db) or `local` (usda_local.db).
    Non-SELECT statements are rejected; app results have secrets/PINs redacted."""
    if which == "app":
        db_path = APP_DB_PATH
    elif which == "local":
        if not usda_local_search.is_available():
            raise HTTPException(status_code=503, detail="usda_local.db not built.")
        db_path = usda_local_search.DB_PATH
    else:
        raise HTTPException(status_code=400, detail="path must be 'app' or 'local'")

    sql = admin_query.validate_select(body.sql)
    columns, rows, truncated = admin_query.run_query(db_path, sql)
    if which == "app":
        rows = admin_query.redact_rows(columns, rows, _secret_values(db))
    return SqlQueryResult(columns=columns, rows=rows, row_count=len(rows), truncated=truncated)
