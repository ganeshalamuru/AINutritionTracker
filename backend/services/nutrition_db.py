"""Nutrient lookup stage.

The vision model identifies a meal's ingredients + weights (it's good at that);
this module turns that ingredient list into real nutrient numbers by looking each
food up in the USDA FoodData Central database (it's good at that). Splitting the two
fixes the core accuracy problem — the model no longer fabricates macro/micro values.

Each item contributes `per_100g_value * grams / 100`; contributions are summed across
all items into the same 7-macro / 17-micro schema the rest of the app uses.

Lookups are cached in SQLite (`food_cache`) so repeated foods cost no API calls and
we stay well under USDA's free-tier ~1,000 req/hour limit.
"""
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from sqlalchemy import text

from database import engine
from logging_config import configure_logging
from services.gemini_service import MACRO_KEYS, ALL_MICRO_KEYS

configure_logging()
logger = logging.getLogger("nutriai.nutrition_db")

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

# Bump to invalidate cached lookups after changing matching logic (main.py purges
# food_cache on startup when app_config's stored version differs from this).
CACHE_VERSION = "4"

# Stripped (after the comma) when retrying a miss with a simpler query.
COOKING_ADJECTIVES = {
    "cooked", "raw", "fried", "boiled", "roasted", "grilled", "steamed",
    "fresh", "baked", "sauteed", "sautéed",
}

# Non-distinctive words: ignored when deriving the "food noun" a match must contain,
# so 'mint leaves' keys on 'mint' (not 'leaves') and 'rice white cooked' keys on 'rice'.
GENERIC_WORDS = {
    "leaves", "leaf", "powder", "ground", "dried", "fresh", "raw", "cooked",
    "fried", "boiled", "roasted", "grilled", "steamed", "baked", "whole",
    "plain", "sliced", "chopped", "oil", "nfs", "white", "red", "green",
}

# Common (esp. Indian) ingredient names the model emits -> a concise, USDA-friendly
# generic/cooked query. The alias only rewrites the SEARCH; results still pass the
# head-noun gate below, and the cache stays keyed by the original ingredient name.
FOOD_ALIASES = {
    "rice": "rice white cooked",
    "white rice": "rice white cooked",
    "cooked rice": "rice white cooked",
    "basmati rice": "rice white cooked",
    "boiled rice": "rice white cooked",
    "brown rice": "brown rice cooked",
    "yogurt": "yogurt plain whole",
    "curd": "yogurt plain whole",
    "dahi": "yogurt plain whole",
    "paneer": "cheese paneer",
    "ghee": "butter ghee",
    "butter": "salted butter",
    "onion": "onions cooked",
    "fried onion": "onions cooked",
    "onion, fried": "onions cooked",
    "onions": "onions cooked",
    "mint": "spearmint fresh",
    "mint leaves": "spearmint fresh",
    "coriander": "coriander leaves raw",
    "cilantro": "coriander leaves raw",
    "tomato": "tomatoes raw",
    "tomatoes": "tomatoes raw",
    "potato": "potatoes boiled",
    "carrot": "carrots raw",
    "carrots": "carrots raw",
    "peas": "peas green cooked",
    "green peas": "peas green cooked",
    "mixed vegetables": "mixed vegetables cooked",
    "vegetables": "mixed vegetables cooked",
    "roti": "chapati roti",
    "chapati": "chapati roti",
    "wheat roti": "chapati roti",
    "naan": "bread naan",
    "dal": "lentils cooked",
    "daal": "lentils cooked",
    "lentils": "lentils cooked",
    # Dals / legumes the decomposition step emits.
    # USDA has no urad/black gram entry — fall back to generic cooked lentils.
    "urad dal": "lentils cooked",
    "urad": "lentils cooked",
    "black gram": "lentils cooked",
    "toor dal": "pigeon peas cooked",
    "tur dal": "pigeon peas cooked",
    "arhar": "pigeon peas cooked",
    "pigeon peas": "pigeon peas cooked",
    "chana dal": "chickpeas cooked",
    "bengal gram": "chickpeas cooked",
    "chickpeas": "chickpeas cooked",
    "moong dal": "mung beans cooked",
    "mung dal": "mung beans cooked",
    "green gram": "mung beans cooked",
    "chicken": "chicken breast cooked roasted",
    "chicken breast": "chicken breast cooked roasted",
    "chicken breast, cooked": "chicken breast cooked roasted",
    "egg": "egg whole cooked",
    "milk": "milk whole",
    "apple": "apples raw",
    "apples": "apples raw",
    "banana": "bananas raw",
    "bananas": "bananas raw",
    # Other base ingredients from decomposition.
    "coconut": "coconut raw",
    "tamarind": "tamarinds raw",
    "green chili": "chili peppers raw",
    "chili": "chili peppers raw",
    "chilli": "chili peppers raw",
    "coffee": "brewed coffee",
    "filter coffee": "brewed coffee",
    "vegetable oil": "vegetable oil nfs",
    "oil": "vegetable oil nfs",
    "sugar": "granulated sugar",
    "semolina": "semolina",
    "rava": "semolina",
    "sooji": "semolina",
}


class UsdaRateLimitError(Exception):
    """USDA rejected the request for exceeding the API key's rate limit.
    Raised (not swallowed) so the meal fails loudly instead of returning zeros."""

# USDA FoodData Central nutrient IDs -> our schema keys (values are per 100g).
FDC_NUTRIENT_MAP = {
    1008: "calories",        # Energy (kcal)
    1003: "protein_g",
    1005: "carbs_g",         # Carbohydrate, by difference
    1004: "fat_g",           # Total lipid (fat)
    1079: "fiber_g",         # Fiber, total dietary
    2000: "sugar_g",         # Total Sugars
    1093: "sodium_mg",
    1106: "vitamin_a_mcg",   # Vitamin A, RAE
    1114: "vitamin_d_mcg",   # Vitamin D (D2 + D3)
    1109: "vitamin_e_mg",    # Vitamin E (alpha-tocopherol)
    1185: "vitamin_k_mcg",   # Vitamin K (phylloquinone)
    1162: "vitamin_c_mg",    # Vitamin C, total ascorbic acid
    1165: "vitamin_b1_mg",   # Thiamin
    1166: "vitamin_b2_mg",   # Riboflavin
    1167: "vitamin_b3_mg",   # Niacin
    1175: "vitamin_b6_mg",   # Vitamin B-6
    1178: "vitamin_b12_mcg", # Vitamin B-12
    1177: "folate_mcg",      # Folate, total
    1087: "calcium_mg",
    1089: "iron_mg",
    1090: "magnesium_mg",
    1092: "potassium_mg",
    1095: "zinc_mg",
    1091: "phosphorus_mg",
}
# Energy is sometimes reported under Atwater factors instead of 1008.
ENERGY_FALLBACK_IDS = (2047, 2048)

# Canned per-meal totals returned in mock mode so the pipeline runs fully offline.
MOCK_MACROS = {
    "calories": 520, "protein_g": 42, "carbs_g": 55, "fat_g": 12,
    "fiber_g": 6, "sugar_g": 4, "sodium_mg": 480,
}
MOCK_MICROS = {
    "vitamin_c_mg": 18, "vitamin_d_mcg": 1.2, "vitamin_b12_mcg": 0.9,
    "folate_mcg": 45, "calcium_mg": 55, "iron_mg": 2.8,
    "magnesium_mg": 62, "potassium_mg": 520,
}


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_mock() -> bool:
    return os.environ.get("MOCK_GEMINI", "").lower() in ("1", "true")


def _normalize(name: str) -> str:
    return " ".join((name or "").lower().split())


def _extract_per_100g(food: dict) -> dict:
    """Pull the nutrients we track from a USDA food record (values are per 100g)."""
    raw = {}
    for n in food.get("foodNutrients", []):
        nid = n.get("nutrientId")
        val = n.get("value")
        if nid is not None and _is_number(val):
            raw[nid] = val

    per_100g = {k: 0.0 for k in MACRO_KEYS + ALL_MICRO_KEYS}
    for nid, key in FDC_NUTRIENT_MAP.items():
        if nid in raw:
            per_100g[key] = float(raw[nid])
    if per_100g["calories"] == 0:
        for alt in ENERGY_FALLBACK_IDS:
            if alt in raw:
                per_100g["calories"] = float(raw[alt])
                break
    return per_100g


# --- cache (food name -> per-100g nutrient profile) ---

_cache_ready = False


def _ensure_cache_table():
    """Create the cache table on first use. main.py also creates it at startup;
    doing it here too keeps the module self-sufficient (e.g. standalone tests)."""
    global _cache_ready
    if _cache_ready:
        return
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS food_cache ("
                "query TEXT PRIMARY KEY, fdc_id INTEGER, nutrients_json TEXT, fetched_at REAL)"
            ))
        _cache_ready = True
    except Exception as e:
        logger.warning("could not ensure food_cache table: %s", e)


def _cache_get(query: str) -> dict | None:
    _ensure_cache_table()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT nutrients_json FROM food_cache WHERE query = :q"),
                {"q": query},
            ).first()
        if row and row[0]:
            return json.loads(row[0])
    except Exception as e:
        logger.warning("cache read failed for %r: %s", query, e)
    return None


def _cache_put(query: str, fdc_id, per_100g: dict):
    _ensure_cache_table()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT OR REPLACE INTO food_cache (query, fdc_id, nutrients_json, fetched_at) "
                    "VALUES (:q, :fid, :j, :ts)"
                ),
                {"q": query, "fid": fdc_id, "j": json.dumps(per_100g), "ts": time.time()},
            )
    except Exception as e:
        logger.warning("cache write failed for %r: %s", query, e)


def _simplify(query: str) -> str:
    """A simpler query to retry a miss with: drop everything after the first comma,
    then strip cooking adjectives. 'onion, fried' -> 'onion'; 'chicken breast, cooked'
    -> 'chicken breast'. Returns '' when it wouldn't change the query."""
    base = query.split(",", 1)[0]
    words = [w for w in base.split() if w not in COOKING_ADJECTIVES]
    simplified = " ".join(words).strip()
    return simplified if simplified and simplified != query else ""


def _aliased(query: str) -> str:
    """Rewrite a known ingredient name to a USDA-friendly generic/cooked query.
    Tries the exact name, the comma-stripped name, and the simplified form."""
    for cand in (query, query.replace(",", "").strip(), _simplify(query)):
        if cand and cand in FOOD_ALIASES:
            return FOOD_ALIASES[cand]
    return query


def _stem(word: str) -> str:
    """Crude singular stem so 'onions'/'onion', 'tomatoes'/'tomato' match."""
    w = word.lower()
    for suf in ("es", "s"):
        if len(w) > 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _food_noun(query: str) -> str:
    """The distinctive food word a real match must contain — the last non-generic
    token. 'mint leaves' -> 'mint'; 'rice white cooked' -> 'rice'; alias values are
    curated so the true food word lands last (e.g. 'yogurt plain whole')."""
    words = [w for w in query.replace(",", " ").split() if w not in GENERIC_WORDS]
    return words[-1] if words else (query.split()[-1] if query.split() else "")


def _pick_best(foods: list, query: str) -> dict | None:
    """Choose the best USDA result for `query`, or None if none is a real match.

    Gate: the description must contain the query's food noun (stem-insensitive) —
    otherwise the result is unrelated (e.g. 'mint leaves' returning 'Amaranth
    leaves') and we'd rather report unmatched than a confident wrong number.
    Rank survivors: food noun as the FIRST word (USDA commodity convention,
    'Rice, ...'/'Yogurt, ...'), then full token coverage, then generic data type,
    then shorter description, then higher relevance score."""
    if not foods:
        return None
    noun = _stem(_food_noun(query))
    tokens = {_stem(t) for t in query.replace(",", " ").split() if t}

    def desc_stems(food):
        return {_stem(w) for w in (food.get("description") or "").lower().replace(",", " ").split()}

    survivors = [f for f in foods if not noun or noun in desc_stems(f)]
    if not survivors:
        return None

    def rank(food: dict):
        words = (food.get("description") or "").lower().replace(",", " ").split()
        stems = {_stem(w) for w in words}
        # Some records (esp. a few Foundation items) come back with no energy value;
        # skip them in favour of a populated entry — a 0-calorie match is useless.
        no_energy = 0 if _extract_per_100g(food)["calories"] > 0 else 1
        not_first = 0 if words and _stem(words[0]) == noun else 1
        covers = 0 if tokens and tokens.issubset(stems) else 1
        type_rank = DATA_TYPE_RANK.get(food.get("dataType"), 99)
        return (no_energy, not_first, covers, type_rank, len(words), -(food.get("score") or 0))

    return min(survivors, key=rank)


def _search_usda(query: str, api_key: str, require_all: bool) -> list:
    """One external call to USDA /foods/search. Logs the request and response, and
    raises UsdaRateLimitError on a throttle. Returns the candidate food list."""
    payload = {
        "query": query, "dataType": USDA_DATA_TYPES,
        "pageSize": USDA_PAGE_SIZE, "requireAllWords": require_all,
    }
    logger.info("request  -> search %r (%s)", query, "strict" if require_all else "loose")
    start = time.monotonic()
    resp = requests.post(
        USDA_SEARCH_URL,
        params={"api_key": api_key or "DEMO_KEY"},
        json=payload,
        timeout=USDA_TIMEOUT,
    )
    elapsed = time.monotonic() - start

    body = {}
    try:
        body = resp.json() or {}
    except Exception:
        pass

    over_limit = (resp.status_code in (429, 403)
                  or (body.get("error") or {}).get("code") == "OVER_RATE_LIMIT")
    if over_limit:
        logger.warning("response <- %r | rate limited (HTTP %d)", query, resp.status_code)
        raise UsdaRateLimitError(f"USDA rate limit (HTTP {resp.status_code}) for {query!r}")

    if resp.status_code != 200:
        logger.warning("response <- %r | HTTP %d | %s", query, resp.status_code, resp.text[:120])
        resp.raise_for_status()

    foods = body.get("foods") or []
    logger.info("response <- %r | %d hits | %.2fs", query, len(foods), elapsed)
    logger.debug("candidates %r: %s", query,
                 [(f.get("dataType"), f.get("fdcId"), f.get("description")) for f in foods[:USDA_PAGE_SIZE]])
    return foods


def lookup_nutrients(item_name: str, api_key: str) -> dict | None:
    """Per-100g nutrient profile for a food name, or None if USDA has no real match.
    Hits the SQLite cache first; only misses reach the USDA API. Raises
    UsdaRateLimitError if the API key is throttled (caller decides how to surface it)."""
    query = _normalize(item_name)
    if not query:
        return None

    cached = _cache_get(query)
    if cached is not None:
        logger.info("cache hit %r", query)
        return cached

    search_q = _aliased(query)
    via = f" (via {search_q!r})" if search_q != query else ""

    try:
        # Strict first (all words must be present) to avoid loosely-related dishes;
        # if that finds nothing, retry the simplified form leniently and let the gate filter.
        foods = _search_usda(search_q, api_key, require_all=True)
        if not foods:
            simpler = _simplify(search_q)
            if simpler:
                logger.info("retry %r (loose)", simpler)
                foods = _search_usda(simpler, api_key, require_all=False)
    except UsdaRateLimitError:
        raise
    except Exception as e:
        logger.warning("lookup failed %r: %s: %s", query, type(e).__name__, e)
        return None

    food = _pick_best(foods, search_q)
    if food is None:
        logger.info("no match %r%s", query, via)
        return None

    per_100g = _extract_per_100g(food)
    logger.info("matched %r%s -> %s [%s]",
                query, via, food.get("description"), food.get("dataType"))
    _cache_put(query, food.get("fdcId"), per_100g)
    return per_100g


def clear_cache():
    """Drop all cached lookups (used when matching logic changes — see CACHE_VERSION)."""
    _ensure_cache_table()
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM food_cache"))
        logger.info("food_cache cleared")
    except Exception as e:
        logger.warning("could not clear food_cache: %s", e)


def nutrients_for_items(items: list[dict], api_key: str) -> tuple[dict, dict, list]:
    """Sum nutrients across an ingredient list.

    Returns (macros, micros, unmatched) where macros/micros are full schema dicts
    (default 0) and unmatched lists the foods USDA couldn't resolve (those
    contribute nothing). In mock mode, returns canned totals without any API call.

    Raises UsdaRateLimitError if USDA throttles the key — the caller maps it to a
    clear error so a rate-limited meal never silently returns zeros.
    """
    if _is_mock():
        logger.info("mock mode -> canned nutrient totals (no USDA call)")
        macros = {k: MOCK_MACROS.get(k, 0) for k in MACRO_KEYS}
        micros = {k: MOCK_MICROS.get(k, 0) for k in ALL_MICRO_KEYS}
        return macros, micros, []

    valid = [it for it in (items or [])
             if (it.get("food") or "").strip() and _is_number(it.get("grams")) and it.get("grams") > 0]

    # One lookup per distinct food name (deduped), run in parallel to cut latency.
    unique_names = list({(it.get("food") or "").strip() for it in valid})
    with ThreadPoolExecutor(max_workers=min(USDA_MAX_WORKERS, len(unique_names) or 1)) as pool:
        results = list(pool.map(lambda name: (name, lookup_nutrients(name, api_key)), unique_names))
    profiles = dict(results)  # name -> per_100g | None  (UsdaRateLimitError propagates out of map)

    totals = {k: 0.0 for k in MACRO_KEYS + ALL_MICRO_KEYS}
    unmatched = []
    for it in valid:
        food = it["food"].strip()
        per_100g = profiles.get(food)
        if per_100g is None:
            if food not in unmatched:
                unmatched.append(food)
            continue
        factor = it["grams"] / 100.0
        for key in totals:
            totals[key] += per_100g.get(key, 0) * factor

    macros = {k: round(totals[k], 2) for k in MACRO_KEYS}
    micros = {k: round(totals[k], 4) for k in ALL_MICRO_KEYS}
    return macros, micros, unmatched
