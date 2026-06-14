"""Public read-only API over the offline USDA search index (backend/usda_local.db).

Always mounted (USDA data isn't sensitive). Thin wrappers over services.usda_local_search:
full-text search and fetch-by-id, with nutrients mapped into the app's macro/micro schema by
reusing usda_service._extract_per_100g — the same extractor Stage 2 uses, so numbers match the
analyzer. Returns 503 when the index hasn't been built (run `python build_usda_db.py`)."""

from fastapi import APIRouter, HTTPException, Query

from core.nutrients import MACRO_KEYS, MICRO_KEYS
from schemas import FoodDetail, FoodSummary, MacrosData, MicrosData
from services import usda_local_search
from services.usda_service import _extract_per_100g

router = APIRouter(prefix="/foods", tags=["foods"])

# API display strings stored in usda_local.db (used to validate the optional filter).
DATA_TYPES = ["Foundation", "SR Legacy", "Survey (FNDDS)"]


def _require_db():
    if not usda_local_search.is_available():
        raise HTTPException(
            status_code=503,
            detail="Offline USDA database not built. Run `python build_usda_db.py` in backend/.",
        )


@router.get("/search", response_model=list[FoodSummary], summary="Search USDA foods (offline)")
def search_foods(
    q: str = Query(min_length=1, description="Food name to search for"),
    data_type: str | None = Query(
        default=None, description="Filter: Foundation | SR Legacy | Survey (FNDDS)"
    ),
    require_all: bool = Query(default=True, description="Require every word to match"),
    limit: int = Query(default=25, ge=1, le=100),
):
    _require_db()
    data_types = [data_type] if data_type in DATA_TYPES else None
    hits = usda_local_search.search(
        q, require_all=require_all, data_types=data_types, page_size=limit
    )
    return [
        FoodSummary(
            fdc_id=f["fdcId"],
            description=f["description"],
            data_type=f["dataType"],
            score=f.get("score") or 0,
        )
        for f in hits
    ]


@router.get("/{fdc_id}", response_model=FoodDetail, summary="Get a USDA food's per-100g nutrients")
def get_food(fdc_id: int):
    _require_db()
    food = usda_local_search.get_food(fdc_id)
    if food is None:
        raise HTTPException(status_code=404, detail=f"No food with fdc_id {fdc_id}")
    per_100g = _extract_per_100g(food)
    return FoodDetail(
        fdc_id=food["fdcId"],
        description=food["description"],
        data_type=food["dataType"],
        macros=MacrosData(**{k: per_100g[k] for k in MACRO_KEYS}),
        micros=MicrosData(**{k: per_100g[k] for k in MICRO_KEYS}),
    )
