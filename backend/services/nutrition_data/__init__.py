"""Reference data for the USDA nutrient-lookup stage (services/usda_service.py).

Pure data only — no logic, no I/O, no module globals. Split out of usda_service.py
so the matching code and the large lookup tables it depends on can be read and
edited independently. Grouped by concern:

  config        — USDA API endpoint + request tuning + cache version
  aliases       — ingredient-name normalization vocabularies (FOOD_ALIASES, word sets)
  nutrient_map  — USDA nutrient IDs -> our schema keys
  mock          — canned totals returned in MOCK_GEMINI mode

`usda_service` re-imports every name below into its own namespace, so the public
surface (e.g. `FOOD_ALIASES`) is unchanged.
"""

from services.nutrition_data.aliases import (
    COOKING_ADJECTIVES,
    DISH_ALIASES,
    FOOD_ALIASES,
    GENERIC_WORDS,
    SIMPLIFY_STRIP_WORDS,
)
from services.nutrition_data.config import (
    DATA_TYPE_RANK,
    DISH_DATA_TYPES,
    USDA_CONNECT_TIMEOUT,
    USDA_DATA_TYPES,
    USDA_MAX_LOOKUPS,
    USDA_MAX_WORKERS,
    USDA_PAGE_SIZE,
    USDA_RETRIES,
    USDA_RETRY_BACKOFF,
    USDA_SEARCH_URL,
    USDA_TIMEOUT,
    USDA_TRANSIENT_STATUS,
)
from services.nutrition_data.mock import (
    MOCK_NUTRIENTS,
)
from services.nutrition_data.nutrient_map import (
    ENERGY_FALLBACK_IDS,
    FDC_NUTRIENT_MAP,
    OMEGA3_IDS,
)

__all__ = [
    "USDA_SEARCH_URL",
    "USDA_DATA_TYPES",
    "DATA_TYPE_RANK",
    "DISH_DATA_TYPES",
    "USDA_PAGE_SIZE",
    "USDA_TIMEOUT",
    "USDA_CONNECT_TIMEOUT",
    "USDA_RETRIES",
    "USDA_RETRY_BACKOFF",
    "USDA_TRANSIENT_STATUS",
    "USDA_MAX_WORKERS",
    "USDA_MAX_LOOKUPS",
    "COOKING_ADJECTIVES",
    "SIMPLIFY_STRIP_WORDS",
    "GENERIC_WORDS",
    "FOOD_ALIASES",
    "DISH_ALIASES",
    "FDC_NUTRIENT_MAP",
    "ENERGY_FALLBACK_IDS",
    "OMEGA3_IDS",
    "MOCK_NUTRIENTS",
]
