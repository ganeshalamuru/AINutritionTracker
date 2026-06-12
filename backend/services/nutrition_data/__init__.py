"""Reference data for the USDA nutrient-lookup stage (services/nutrition_db.py).

Pure data only — no logic, no I/O, no module globals. Split out of nutrition_db.py
so the matching code and the large lookup tables it depends on can be read and
edited independently. Grouped by concern:

  config        — USDA API endpoint + request tuning + cache version
  aliases       — ingredient-name normalization vocabularies (FOOD_ALIASES, word sets)
  nutrient_map  — USDA nutrient IDs -> our schema keys
  mock          — canned totals returned in MOCK_GEMINI mode

`nutrition_db` re-imports every name below into its own namespace, so the public
surface (e.g. `nd.FOOD_ALIASES`, `nd.CACHE_VERSION`) is unchanged.
"""
from services.nutrition_data.config import (
    USDA_SEARCH_URL,
    USDA_DATA_TYPES,
    DATA_TYPE_RANK,
    USDA_PAGE_SIZE,
    USDA_TIMEOUT,
    USDA_MAX_WORKERS,
    USDA_MAX_LOOKUPS,
    CACHE_VERSION,
)
from services.nutrition_data.aliases import (
    COOKING_ADJECTIVES,
    SIMPLIFY_STRIP_WORDS,
    GENERIC_WORDS,
    FOOD_ALIASES,
)
from services.nutrition_data.nutrient_map import (
    FDC_NUTRIENT_MAP,
    ENERGY_FALLBACK_IDS,
)
from services.nutrition_data.mock import (
    MOCK_MACROS,
    MOCK_MICROS,
)

__all__ = [
    "USDA_SEARCH_URL",
    "USDA_DATA_TYPES",
    "DATA_TYPE_RANK",
    "USDA_PAGE_SIZE",
    "USDA_TIMEOUT",
    "USDA_MAX_WORKERS",
    "USDA_MAX_LOOKUPS",
    "CACHE_VERSION",
    "COOKING_ADJECTIVES",
    "SIMPLIFY_STRIP_WORDS",
    "GENERIC_WORDS",
    "FOOD_ALIASES",
    "FDC_NUTRIENT_MAP",
    "ENERGY_FALLBACK_IDS",
    "MOCK_MACROS",
    "MOCK_MICROS",
]
