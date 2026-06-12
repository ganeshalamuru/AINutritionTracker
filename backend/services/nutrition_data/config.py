"""USDA FoodData Central API endpoint and request tuning."""

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"

# Foundation + SR Legacy have the fullest micro profiles and are the most generic
# (preferred when picking a match); FNDDS (Survey) adds many prepared/mixed dishes.
# Branded is excluded — it's mostly label-only macros.
USDA_DATA_TYPES = ["Foundation", "SR Legacy", "Survey (FNDDS)"]

# Lower rank = preferred. Generic analytical entries beat consumed/mixed dishes.
DATA_TYPE_RANK = {"Foundation": 0, "SR Legacy": 1, "Survey (FNDDS)": 2}

USDA_PAGE_SIZE = 5          # fetch a few candidates so we can pick the best match
USDA_TIMEOUT = 10
USDA_MAX_WORKERS = 4        # parallel ingredient lookups per meal

# Cap on distinct UNCACHED ingredients looked up per meal (largest portions win).
# Cached lookups are free and never count against this. Keeps per-meal API usage
# bounded; ingredients beyond the cap are reported as "skipped" (counted as 0).
USDA_MAX_LOOKUPS = 8

# Bump to invalidate cached lookups after changing matching logic (main.py purges
# food_cache on startup when app_config's stored version differs from this).
CACHE_VERSION = "5"
