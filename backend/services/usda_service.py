"""Nutrient lookup stage (Stage 2 of the two-stage nutrition pipeline).

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
from requests.adapters import HTTPAdapter
from sqlalchemy import text

from core.database import engine
from core.logging_config import configure_logging
from core.nutrients import NUTRIENT_KEYS
from core.request_context import request_id_var, user_id_var
from services import usda_local_search

# Reference data (lookup tables, config constants) lives in services/nutrition_data/.
# Re-imported here so the public surface (USDA_*, FOOD_ALIASES, ...) and consumers
# (check_aliases.py, tests) keep working unchanged. Every name below is used in this module.
from services.nutrition_data import (
    DATA_TYPE_RANK,
    DISH_ALIASES,
    DISH_DATA_TYPES,
    ENERGY_FALLBACK_IDS,
    FDC_NUTRIENT_MAP,
    FOOD_ALIASES,
    GENERIC_WORDS,
    MOCK_NUTRIENTS,
    OMEGA3_IDS,
    SIMPLIFY_STRIP_WORDS,
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

configure_logging()
logger = logging.getLogger("nutriai.nutrition_db")


def _bind_log_context():
    """Snapshot the request's correlation ids so pool workers can re-apply them.

    The shared ThreadPoolExecutor's worker threads don't inherit the request's contextvars
    (unlike asyncio.to_thread), so without this their `usda-lookup_*` log lines would lose
    the request_id/user_id. We capture the ids here (on the calling thread, which is
    inside the request context) and return a wrapper that sets them before running each
    pooled task. Pool threads are reused, so every task re-sets them — no reset needed."""
    rid = request_id_var.get()
    uid = user_id_var.get()

    def run(fn):
        request_id_var.set(rid)
        user_id_var.set(uid)
        return fn()

    return run


# --- shared USDA client (a pooled Session + a worker pool, with the key on a header) ---


class UsdaClient:
    """Shared USDA HTTP client: a pooled requests.Session (key on the X-Api-Key header) plus a
    ThreadPoolExecutor for parallel per-meal lookups. Built ONCE and reused across every
    /analyze — never per request. Both pools are key-independent, so a key change only updates
    the header (set_api_key); nothing is rebuilt.

    A meal fires up to ~8 ingredient + dish lookups, each a POST to api.nal.usda.gov. The shared
    Session keeps the HTTPS connection alive across the parallel workers and across meals (no
    fresh TCP/TLS handshake per call); the adapter pool is sized to the worker count. We do NOT
    use urllib3's Retry (its default allowed_methods excludes POST, so it would silently never
    retry the search) — transient errors are retried explicitly in _search_usda (see
    USDA_RETRIES), which also keeps the retry in the logs."""

    def __init__(self, api_key: str = ""):
        self.session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=USDA_MAX_WORKERS, pool_maxsize=USDA_MAX_WORKERS, max_retries=0
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)
        # Key on X-Api-Key (api.data.gov supports it and prefers it over ?api_key= — keeps the
        # key out of request URLs/logs); a descriptive User-Agent replaces python-requests'.
        self.session.headers.update(
            {"X-Api-Key": api_key or "DEMO_KEY", "User-Agent": "NutriAI/1.0"}
        )
        # thread_name_prefix keeps each worker's log lines distinguishable (%(threadName)s).
        self.pool = ThreadPoolExecutor(
            max_workers=USDA_MAX_WORKERS, thread_name_prefix="usda-lookup"
        )

    def set_api_key(self, api_key: str):
        """Point the client at a new USDA key — atomic header update, no session/pool rebuild."""
        self.session.headers["X-Api-Key"] = api_key or "DEMO_KEY"


# Built once at import (self-sufficient for tests/scripts); reload_client sets the real key at
# startup and on config change. The connection/worker pools live for the process lifetime.
_client = UsdaClient()

# Which Stage-2 backend resolves foods: False -> online USDA API (the default, and what the
# tests exercise), True -> the offline SQLite FTS5 index (services/usda_local_search). Set from
# the `nutrition_source` config row by reload_client at startup and on every PUT /api/config.
_use_local = False


def configure(api_key: str):
    """Set the shared client's USDA key. Used by reload_client (the app path) and by standalone
    scripts. Just updates the X-Api-Key header — the connection and worker pools are reused."""
    _client.set_api_key(api_key)
    logger.info("usda client configured (key set=%s)", bool(api_key))


def reload_client(db):
    """Point the shared USDA client at the currently configured key AND select the active
    Stage-2 backend (online API vs offline local index) from `nutrition_source`. Called once at
    startup (core.lifespan) and after every PUT /api/config, like vision_service.reload_clients."""
    from core import config  # local import keeps core out of this module's top-level graph

    configure(config.get_usda_key(db))
    global _use_local
    _use_local = config.get_nutrition_source(db) == "offline"
    logger.info(
        "nutrition source: %s", "offline (local FTS5)" if _use_local else "online (USDA API)"
    )
    if _use_local and not usda_local_search.is_available():
        logger.warning(
            "offline nutrition source selected but %s is missing — run "
            "`python build_usda_db.py` (lookups will report unmatched until it exists)",
            usda_local_search.DB_PATH,
        )


class UsdaRateLimitError(Exception):
    """USDA rejected the request for exceeding the API key's rate limit.
    Raised (not swallowed) so the meal fails loudly instead of returning zeros."""


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_mock() -> bool:
    return os.environ.get("MOCK_GEMINI", "").lower() in ("1", "true")


def _normalize(name: str) -> str:
    return " ".join((name or "").lower().split())


def _ckey(query: str) -> str:
    """Cache key namespaced by the active nutrition source. Online and offline can resolve the
    same name to different nutrients, so prefix offline keys with 'local::' (composes with the
    existing 'dish::' prefix) to keep the two backends' cached results from colliding in
    food_cache. No purge needed when the user toggles the source in Settings."""
    return ("local::" + query) if _use_local else query


def _extract_per_100g(food: dict) -> dict:
    """Pull the nutrients we track from a USDA food record (values are per 100g)."""
    raw = {}
    for n in food.get("foodNutrients", []):
        nid = n.get("nutrientId")
        val = n.get("value")
        if nid is not None and _is_number(val):
            raw[nid] = val

    per_100g = {k: 0.0 for k in NUTRIENT_KEYS}
    for nid, key in FDC_NUTRIENT_MAP.items():
        if nid in raw:
            per_100g[key] = float(raw[nid])
    if per_100g["calories"] == 0:
        for alt in ENERGY_FALLBACK_IDS:
            if alt in raw:
                per_100g["calories"] = float(raw[alt])
                break
    # Omega-3 (EPA + DHA) is the sum of two USDA nutrients; the id->key map can't sum.
    per_100g["omega3_g"] = sum(float(raw[nid]) for nid in OMEGA3_IDS if nid in raw)
    return per_100g


# --- cache (food name -> per-100g nutrient profile) ---

_cache_ready = False

# Stored as the cached value for a DEFINITIVE miss (the search succeeded but returned 0
# hits / no acceptable match). Lets repeat lookups of a known-bad name short-circuit
# without re-hitting the slow USDA API. Transient failures (timeouts/connection errors)
# are deliberately NOT cached this way — they must be retried on the next analyze.
_MISS = {"__miss__": True}


def _ensure_cache_table():
    """Create the cache table on first use. The lifespan also creates it at startup;
    doing it here too keeps the module self-sufficient (e.g. standalone tests)."""
    global _cache_ready
    if _cache_ready:
        return
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS food_cache ("
                    "query TEXT PRIMARY KEY, fdc_id INTEGER, nutrients_json TEXT, fetched_at REAL)"
                )
            )
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
    words = [w for w in base.split() if w not in SIMPLIFY_STRIP_WORDS]
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


def _search_usda(query: str, require_all: bool, data_types: list | None = None) -> list:
    """One external call to USDA /foods/search. Logs the request and response, and
    raises UsdaRateLimitError on a throttle. Returns the candidate food list. The API key
    rides on the shared Session's X-Api-Key header (set at client-build time, see configure).
    `data_types` defaults to the ingredient set; the dish lookup passes DISH_DATA_TYPES.

    When the offline backend is selected (nutrition_source = "offline"), this resolves against
    the local SQLite FTS5 index instead, returning the identical candidate shape — so all the
    matching/caching code below is unchanged."""
    if _use_local:
        return usda_local_search.search(
            query, require_all=require_all, data_types=data_types or USDA_DATA_TYPES
        )

    payload = {
        "query": query,
        "dataType": data_types or USDA_DATA_TYPES,
        "pageSize": USDA_PAGE_SIZE,
        "requireAllWords": require_all,
    }
    logger.info("request  -> search %r (%s)", query, "strict" if require_all else "loose")
    start = time.monotonic()
    # Retry transient network failures (Timeout/ConnectionError) on a fresh socket; USDA
    # search stalls intermittently and a retry usually clears it. A transient server-side
    # status (gateway HTML 404 / 5xx) is retried the same way. Rate limits (429/403) and a
    # persistent bad status come back as a real response and are handled below (not retried).
    for attempt in range(USDA_RETRIES + 1):
        try:
            resp = _client.session.post(
                USDA_SEARCH_URL,
                json=payload,
                timeout=(USDA_CONNECT_TIMEOUT, USDA_TIMEOUT),
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < USDA_RETRIES:
                logger.warning(
                    "retry %d/%d <- search %r | %s: %s",
                    attempt + 1,
                    USDA_RETRIES,
                    query,
                    type(e).__name__,
                    e,
                )
                time.sleep(USDA_RETRY_BACKOFF * (attempt + 1))
                continue
            raise
        # Transient gateway hiccup: USDA occasionally serves an HTML 404/5xx instead of JSON.
        if resp.status_code in USDA_TRANSIENT_STATUS and attempt < USDA_RETRIES:
            logger.warning(
                "retry %d/%d <- search %r | HTTP %d",
                attempt + 1,
                USDA_RETRIES,
                query,
                resp.status_code,
            )
            time.sleep(USDA_RETRY_BACKOFF * (attempt + 1))
            continue
        break
    elapsed = time.monotonic() - start

    body = {}
    try:
        body = resp.json() or {}
    except Exception:
        pass

    over_limit = (
        resp.status_code in (429, 403) or (body.get("error") or {}).get("code") == "OVER_RATE_LIMIT"
    )
    if over_limit:
        logger.warning("response <- %r | rate limited (HTTP %d)", query, resp.status_code)
        raise UsdaRateLimitError(f"USDA rate limit (HTTP {resp.status_code}) for {query!r}")

    if resp.status_code != 200:
        logger.warning("response <- %r | HTTP %d | %s", query, resp.status_code, resp.text[:120])
        resp.raise_for_status()

    foods = body.get("foods") or []
    logger.info("response <- %r | %d hits | %.2fs", query, len(foods), elapsed)
    logger.debug(
        "candidates %r: %s",
        query,
        [(f.get("dataType"), f.get("fdcId"), f.get("description")) for f in foods[:USDA_PAGE_SIZE]],
    )
    return foods


def lookup_nutrients(item_name: str) -> dict | None:
    """Per-100g nutrient profile for a food name, or None if USDA has no real match.
    Hits the SQLite cache first; only misses reach the USDA API (the key is baked into the
    shared client). Raises UsdaRateLimitError if the key is throttled (caller decides how to
    surface it)."""
    query = _normalize(item_name)
    if not query:
        return None

    cached = _cache_get(_ckey(query))
    if cached is not None:
        if cached.get("__miss__"):
            logger.info("cache hit %r (known miss)", query)
            return None
        logger.info("cache hit %r", query)
        return cached

    search_q = _aliased(query)
    via = f" (via {search_q!r})" if search_q != query else ""

    try:
        # Strict first (all words must be present) to avoid loosely-related dishes;
        # if that finds nothing, retry the simplified form leniently and let the gate filter.
        foods = _search_usda(search_q, require_all=True)
        if not foods:
            simpler = _simplify(search_q)
            if simpler:
                logger.info("retry %r (loose)", simpler)
                foods = _search_usda(simpler, require_all=False)
    except UsdaRateLimitError:
        raise
    except Exception as e:
        logger.warning("lookup failed %r: %s: %s", query, type(e).__name__, e)
        return None

    food = _pick_best(foods, search_q)
    if food is None:
        logger.info("no match %r%s", query, via)
        _cache_put(_ckey(query), None, _MISS)
        return None

    per_100g = _extract_per_100g(food)
    logger.info(
        "matched %r%s -> %s [%s]", query, via, food.get("description"), food.get("dataType")
    )
    _cache_put(_ckey(query), food.get("fdcId"), per_100g)
    return per_100g


def lookup_dish(dish_name: str) -> dict | None:
    """Per-100g nutrient profile for a whole DISH, or None if USDA's FNDDS has no real
    match (caller then decomposes the dish into ingredients). Mirrors lookup_nutrients
    but rewrites via DISH_ALIASES and searches the dish data types. Cached separately
    (a 'dish::' key prefix) so a dish and an ingredient of the same name don't collide.
    Raises UsdaRateLimitError if the key is throttled."""
    name = _normalize(dish_name)
    if not name:
        return None

    cache_key = _ckey("dish::" + name)
    cached = _cache_get(cache_key)
    if cached is not None:
        if cached.get("__miss__"):
            logger.info("cache hit %r (dish, known miss)", name)
            return None
        logger.info("cache hit %r (dish)", name)
        return cached

    search_q = DISH_ALIASES.get(name, name)
    via = f" (via {search_q!r})" if search_q != name else ""

    try:
        foods = _search_usda(search_q, require_all=True, data_types=DISH_DATA_TYPES)
        if not foods:
            simpler = _simplify(search_q)
            if simpler:
                logger.info("retry %r (dish, loose)", simpler)
                foods = _search_usda(simpler, require_all=False, data_types=DISH_DATA_TYPES)
    except UsdaRateLimitError:
        raise
    except Exception as e:
        logger.warning("dish lookup failed %r: %s: %s", name, type(e).__name__, e)
        return None

    food = _pick_best(foods, search_q)
    if food is None:
        logger.info("no dish match %r%s", name, via)
        _cache_put(cache_key, None, _MISS)
        return None

    per_100g = _extract_per_100g(food)
    logger.info(
        "matched dish %r%s -> %s [%s]", name, via, food.get("description"), food.get("dataType")
    )
    _cache_put(cache_key, food.get("fdcId"), per_100g)
    return per_100g


def _uncached_dish(name: str) -> bool:
    return _cache_get(_ckey("dish::" + _normalize(name))) is None


def clear_cache():
    """Drop all cached lookups (used when matching logic changes — see CACHE_VERSION)."""
    _ensure_cache_table()
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM food_cache"))
        logger.info("food_cache cleared")
    except Exception as e:
        logger.warning("could not clear food_cache: %s", e)


def _ingredient_query(it: dict) -> str:
    """The USDA search/cache key for a decomposed ingredient: the Stage-1 generic
    `usda_name` (a model-suggested USDA-friendly name) when present, else the visible
    `food` label. Display, status, and the unmatched/skipped reports all stay keyed on
    `food`; only the actual lookup + cache use this query."""
    return (it.get("usda_name") or "").strip() or (it.get("food") or "").strip()


def _sum_ingredients(items: list[dict], budget: int) -> tuple[dict, list, list, list]:
    """Decomposition path: look each base ingredient up in USDA, scale by grams, sum.

    Each ingredient is searched by its `usda_name` query (see _ingredient_query); the
    budget/cache dedupe on that query so two dishes sharing a generic name cost one
    lookup. Cached lookups are free; only `budget` distinct *uncached* queries are looked
    up (largest portions first), the rest go to `skipped`. Returns
    (totals, unmatched, skipped, lines) where unmatched/skipped are visible `food` labels
    and lines is one {food, grams, source:"ingredient"} entry per valid ingredient (for
    the UI breakdown). Raises UsdaRateLimitError on throttle.
    """
    totals = {k: 0.0 for k in NUTRIENT_KEYS}
    lines: list = []
    unmatched: list = []

    valid = [
        it
        for it in (items or [])
        if (it.get("food") or "").strip() and _is_number(it.get("grams")) and it.get("grams") > 0
    ]
    if not valid:
        return totals, unmatched, [], lines

    # Total grams per distinct query — used to prioritize the lookup budget.
    grams_by_query: dict[str, float] = {}
    for it in valid:
        grams_by_query[_ingredient_query(it)] = (
            grams_by_query.get(_ingredient_query(it), 0.0) + it["grams"]
        )

    cached = {q for q in grams_by_query if _cache_get(_ckey(_normalize(q))) is not None}
    uncached = sorted(
        (q for q in grams_by_query if q not in cached),
        key=lambda q: grams_by_query[q],
        reverse=True,
    )
    budget = max(budget, 0)
    to_lookup = list(cached) + uncached[:budget]
    skipped_queries = set(uncached[budget:])
    if skipped_queries:
        logger.info(
            "lookup cap reached -> skipping %d smaller ingredient(s): %s",
            len(skipped_queries),
            sorted(skipped_queries),
        )

    # Deduped lookups run in parallel on the shared pool to cut latency.
    # (UsdaRateLimitError raised by a worker propagates when we iterate the results.)
    # _bind_log_context() carries the request_id/user_id into the pool workers' logs.
    run_in_ctx = _bind_log_context()
    results = list(
        _client.pool.map(lambda q: run_in_ctx(lambda: (q, lookup_nutrients(q))), to_lookup)
    )
    profiles = dict(results)  # query -> per_100g | None

    skipped: list = []
    for it in valid:
        food = it["food"].strip()
        query = _ingredient_query(it)
        lines.append({"food": food, "grams": it["grams"], "source": "ingredient"})
        if query in skipped_queries:
            if food not in skipped:
                skipped.append(food)
            continue
        per_100g = profiles.get(query)
        if per_100g is None:
            if food not in unmatched:
                unmatched.append(food)
            continue
        factor = it["grams"] / 100.0
        for key in totals:
            totals[key] += per_100g.get(key, 0) * factor

    return totals, unmatched, skipped, lines


def nutrients_for_meal(dishes: list[dict]) -> tuple[dict, list, list, list]:
    """Sum nutrients across a meal's dishes, dish-first.

    For each dish we try a whole-dish USDA lookup (lookup_dish); a dish that matches
    contributes its per-100g profile scaled by the dish's portion grams. Dishes USDA
    has no dish-level match for (or with no portion weight) fall back to summing their
    base-ingredient breakdown — so coverage is never worse than pure decomposition.

    Returns (nutrients, unmatched, skipped, breakdown):
      - nutrients: the flat full-schema nutrient totals dict (default 0)
      - unmatched: base ingredients USDA couldn't resolve (from the fallback path)
      - skipped: ingredients not looked up because the meal exceeded the per-meal
        uncached-lookup budget (USDA_MAX_LOOKUPS), largest portions kept
      - breakdown: the dish-grouped resolution for the UI — one entry per dish:
        {name, grams, matched, nutrients, ingredients:[{food, grams, status}]} where
        `matched` is True if the whole dish resolved in USDA (its ingredients then carry
        status "not_looked_up"), and each fallback ingredient's status is
        "matched" | "unmatched" | "skipped". `nutrients` is the dish's own subtotal (flat
        full-schema dict); summed across dishes it equals the meal totals, so the client
        can rescale a dish by its edited portion without re-querying USDA.
    In mock mode returns canned totals + one matched entry per dish, no API call. Raises
    UsdaRateLimitError if USDA throttles the key.
    """
    if _is_mock():
        logger.info("mock mode -> canned nutrient totals (no USDA call)")
        nutrients = {k: MOCK_NUTRIENTS.get(k, 0) for k in NUTRIENT_KEYS}
        mock_dishes = [d for d in (dishes or []) if (d.get("name") or "").strip()]
        # Split the canned totals across dishes proportionally by grams (equal split if
        # no dish carries a weight) so each dish has a per-dish subtotal for the editing UI.
        weights = [float(d.get("grams") or 0) for d in mock_dishes]
        total_w = sum(weights)
        n = len(mock_dishes)
        shares = [(w / total_w if total_w > 0 else 1.0 / n) for w in weights] if n else []
        breakdown = []
        for d, share in zip(mock_dishes, shares, strict=True):
            breakdown.append(
                {
                    "name": d["name"].strip(),
                    "grams": d.get("grams") or 0,
                    "matched": True,
                    "nutrients": {k: round(nutrients[k] * share, 4) for k in NUTRIENT_KEYS},
                    "ingredients": [
                        {
                            "food": (it.get("food") or "").strip(),
                            "grams": it.get("grams") or 0,
                            "status": "not_looked_up",
                        }
                        for it in (d.get("items") or [])
                        if (it.get("food") or "").strip()
                    ],
                }
            )
        return nutrients, [], [], breakdown

    totals = {k: 0.0 for k in NUTRIENT_KEYS}
    budget = USDA_MAX_LOOKUPS

    valid_dishes = [d for d in (dishes or []) if (d.get("name") or "").strip()]

    # Phase A — dish-first, but only for CURATED dishes (names in DISH_ALIASES, confirmed
    # to exist in USDA's FNDDS). A speculative whole-dish lookup for an un-curated name
    # almost always misses and just burns a slow API call, so those skip straight to
    # Phase B decomposition. Cached dish lookups are free; cap uncached ones at the budget,
    # largest portions first. Dishes with no portion weight also skip to Phase B.
    dish_candidates = [
        d
        for d in valid_dishes
        if (d.get("grams") or 0) > 0 and _normalize(d["name"]) in DISH_ALIASES
    ]
    dish_cached = [d for d in dish_candidates if not _uncached_dish(d["name"])]
    dish_uncached = sorted(
        (d for d in dish_candidates if _uncached_dish(d["name"])),
        key=lambda d: d["grams"],
        reverse=True,
    )
    dish_lookup = dish_cached + dish_uncached[:budget]
    budget -= min(len(dish_uncached), budget)

    # Parallel dish lookups (UsdaRateLimitError propagates when we iterate).
    run_in_ctx = _bind_log_context()
    dish_pairs = list(
        zip(
            dish_lookup,
            _client.pool.map(lambda d: run_in_ctx(lambda: lookup_dish(d["name"])), dish_lookup),
            strict=True,
        )
    )
    matched_ids = set()
    dish_profile: dict[int, dict] = {}  # id(dish) -> per-100g profile, for per-dish subtotals
    for d, per_100g in dish_pairs:
        if per_100g is None:
            continue
        grams = d["grams"]
        factor = grams / 100.0
        for key in totals:
            totals[key] += per_100g.get(key, 0) * factor
        matched_ids.add(id(d))
        dish_profile[id(d)] = per_100g

    # Phase B — decompose every dish that didn't match at the dish level (includes
    # dishes with no portion weight and any beyond the dish budget).
    fallback_items: list = []
    for d in valid_dishes:
        if id(d) not in matched_ids:
            fallback_items.extend(d.get("items") or [])

    ing_totals, unmatched, skipped, _ = _sum_ingredients(fallback_items, budget)
    for key in totals:
        totals[key] += ing_totals[key]

    # Assemble the dish-grouped breakdown for the UI. A matched dish highlights its name
    # (ingredients were not looked up -> "not_looked_up"); an unmatched dish carries each
    # decomposed ingredient's outcome (name-based, since lookups are deduped per meal).
    # Each dish also gets a per-dish nutrient subtotal (so the client can scale a dish's
    # nutrients by its edited portion without re-querying USDA). No new lookups: a matched
    # dish reuses its dish profile; a decomposed dish reads each matched ingredient's
    # already-cached per-100g profile. The subtotals sum to the meal totals above.
    unmatched_set, skipped_set = set(unmatched), set(skipped)
    breakdown: list = []
    for d in valid_dishes:
        matched = id(d) in matched_ids
        ingredients = []
        dish_totals = {k: 0.0 for k in NUTRIENT_KEYS}
        if matched:
            per_100g = dish_profile.get(id(d)) or {}
            factor = (d.get("grams") or 0) / 100.0
            for key in dish_totals:
                dish_totals[key] = per_100g.get(key, 0) * factor
        for it in d.get("items") or []:
            food = (it.get("food") or "").strip()
            if not food:
                continue
            # Per-ingredient subtotal: non-zero only for a resolved ingredient of a
            # decomposed dish, so the client can rescale/remove it independently. Stays 0
            # for not_looked_up/unmatched/skipped. Summed, these equal the dish subtotal.
            ing_sub = {k: 0.0 for k in NUTRIENT_KEYS}
            if matched:
                status = "not_looked_up"
            elif food in skipped_set:
                status = "skipped"
            elif food in unmatched_set:
                status = "unmatched"
            else:
                status = "matched"
                per_100g = _cache_get(_ckey(_normalize(_ingredient_query(it))))
                if per_100g and not per_100g.get("__miss__"):
                    factor = (it.get("grams") or 0) / 100.0
                    for key in dish_totals:
                        val = per_100g.get(key, 0) * factor
                        dish_totals[key] += val
                        ing_sub[key] = val
            ingredients.append(
                {
                    "food": food,
                    "grams": it.get("grams") or 0,
                    "status": status,
                    "nutrients": {k: round(ing_sub[k], 4) for k in NUTRIENT_KEYS},
                }
            )
        breakdown.append(
            {
                "name": d["name"].strip(),
                "grams": d.get("grams") or 0,
                "matched": matched,
                "nutrients": {k: round(dish_totals[k], 4) for k in NUTRIENT_KEYS},
                "ingredients": ingredients,
            }
        )

    nutrients = {k: round(totals[k], 4) for k in NUTRIENT_KEYS}
    return nutrients, unmatched, skipped, breakdown
