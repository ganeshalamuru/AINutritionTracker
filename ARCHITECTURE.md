# NutriAI — Architecture

How the code is organized and why. For session history, design rationale, and the
running list of fixes, see `HANDOFF.md`. This document is about **structure**: the
layers, what each one is responsible for, and how a request flows through them.

---

## The big picture

NutriAI is a photo-to-nutrition tracker. You photograph a meal; a **vision model**
identifies each **dish** (with a fallback base-ingredient breakdown and gram weights);
the **USDA FoodData Central** database supplies the real per-100g nutrient numbers; the
app scales and sums them and stores the meal. This split — *perception* by the LLM,
*facts* from USDA — is the core design decision (the LLM hallucinated nutrients when
asked to do both). It is the **two-stage nutrition pipeline** and everything in the
backend is arranged around it.

Stage 2 is **dish-first**: it looks the whole dish up in USDA's FNDDS database (which
carries many composite dishes, including Indian ones like idli/dosa/sambar) and only
**decomposes a dish into its base ingredients when no dish-level match exists**. A whole
"idli" entry scaled by the portion weight is far more accurate than summing mis-stated
"cooked rice + cooked lentils" — and decomposition remains the safety net for anything
FNDDS doesn't cover.

```
 photo ─> [Stage 1: vision_service] ─dishes(+ingredient fallback)─> [Stage 2: usda_service] ─> macros+micros ─> DB
           (Groq / Gemini / Ollama)                                   dish-first, else decompose
                                                                      (USDA FNDDS + SQLite cache)
```

---

## Layered backend

The backend is FastAPI + SQLAlchemy + SQLite, organized into four layers. **Dependencies
point one way: `routers → services → core → (models, schemas)`.** `core` never imports
from `services` or `routers`; `schemas` is a leaf (imports nothing from the app).

```
backend/
├── main.py                  # entrypoint: load env, configure logging, assemble routers, serve frontend
│
├── core/                    # infrastructure & cross-cutting concerns (no business logic)
│   ├── database.py          #   SQLAlchemy engine (pool_pre_ping + SQLite WAL/busy_timeout pragmas), SessionLocal, Base, get_db
│   ├── logging_config.py    #   configure_logging(): one timestamped formatter for app + uvicorn
│   ├── config.py            #   app_config table access + vision defaults + filesystem paths
│   ├── nutrients.py         #   SINGLE SOURCE for the 7-macro/17-micro schema + convert/sum helpers
│   └── lifespan.py          #   startup/shutdown: create tables, migrate, prep cache, seed config, build vision clients
│
├── models.py                # SQLAlchemy ORM: Profile, Meal, Macros, Micros, AppConfig
├── schemas.py               # Pydantic request/response models (leaf module): AnalyzeResponse, DishBreakdown, ...
│
├── routers/                 # thin HTTP layer — parse request, call a service, return result
│   ├── profiles.py          #   /api/profiles ...
│   ├── meals.py             #   /api/meals ...   (analyze, log, timeline, group, detail)
│   ├── nutrition.py         #   /api/nutrition/daily | /monthly
│   └── config.py            #   /api/config (GET/PUT keys + vision provider/model; rebuilds vision clients on change)
│
└── services/                # business logic — where the work actually happens
    ├── vision_service.py    #   Stage 1: dispatch photo to a vision provider -> dish list (+fallback ingredients); shared clients
    ├── usda_service.py      #   Stage 2: dish-first USDA lookup, matching, SQLite cache (+ negative caching), shared pool + Session
    ├── meal_service.py      #   analyze orchestration + meal CRUD + timeline/group read models
    ├── summary_service.py   #   daily/monthly aggregation
    └── nutrition_data/      #   pure reference data (no logic) used by usda_service:
        ├── config.py        #     USDA endpoint + tuning (timeouts/retries) + DISH_DATA_TYPES + USDA_MAX_LOOKUPS + CACHE_VERSION
        ├── aliases.py       #     FOOD_ALIASES + DISH_ALIASES + word-set vocabularies for name normalization
        ├── nutrient_map.py  #     USDA nutrientId -> our schema key
        └── mock.py          #     canned totals for MOCK_GEMINI mode
```

### Layer responsibilities

- **`core/`** — infrastructure only. Database session, logging, the nutrient schema,
  config-table access, and the FastAPI lifespan. No request handling, no domain rules.
  - `core/nutrients.py` is the **single source of truth** for `MACRO_KEYS` / `MICRO_KEYS`
    and the `to_macros_data` / `to_micros_data` / `sum_macros` / `sum_micros` helpers.
    These lists used to be hand-copied into three modules; now everyone imports them.
  - `core/config.py` is the **single home for `app_config` access** (`get_value`,
    `set_value`, `get_api_key`, `get_vision_config`, `get_usda_key`, `seed_defaults`)
    and also holds the vision **defaults** (`DEFAULT_PROVIDER`/`DEFAULT_MODEL`) and the
    filesystem path constants (`UPLOADS_DIR`, `DIST_DIR`, `BACKEND_DIR`).
- **`models.py` / `schemas.py`** — the persistence shape and the wire shape, kept
  separate. `schemas.py` imports nothing from the app, so `core.nutrients` can depend
  on it without a cycle.
- **`routers/`** — one file per resource. Each handler is a thin wrapper: read the
  request, call a service function, return its result. Routers own only HTTP concerns
  (paths, methods, `response_model`, dependency injection of `get_db`).
- **`services/`** — all domain logic. This is where `db` is used, queries are run,
  external APIs are called, and results are assembled into schema objects.

---

## Request flows

**`POST /api/meals/analyze`** (the heart of the app)
1. `routers/meals.py` reads the uploaded image bytes, calls `meal_service.analyze_image`.
2. `meal_service` reads the configured provider/key (`core.config`), saves a temp image,
   and runs **Stage 1** — `vision_service.analyze_meal_image` in a worker thread
   (`asyncio.to_thread`, so the event loop never blocks). The vision model returns a list
   of dishes, each with a portion weight and a fallback base-ingredient breakdown.
3. It then runs **Stage 2** — `usda_service.nutrients_for_meal` (also off-thread),
   **dish-first**: a whole-dish lookup is attempted only for **curated** dishes (name in
   `DISH_ALIASES`, confirmed to exist in FNDDS) — un-curated names skip the speculative call
   and decompose straight to ingredients via `_sum_ingredients` (alias → head-noun gate →
   scale → sum). All lookups run in parallel on a **shared module-level `ThreadPoolExecutor`**
   over a shared `requests.Session`; a per-meal uncached-lookup budget (`USDA_MAX_LOOKUPS`)
   bounds API usage. Both positive matches **and definitive misses** are cached (negative
   caching) so a known-bad name isn't re-queried; transient timeouts are retried, not cached.
4. The assembled `AnalyzeResponse` goes back as a **dish-grouped breakdown**:
   `dishes: [{name, grams, matched, macros, micros, ingredients: [{food, grams, status}]}]`
   where `status` is `matched | unmatched | skipped | not_looked_up`, plus aggregate
   `unmatched`/`skipped` name lists. Each dish also carries its **own nutrient subtotal**
   (`macros`/`micros`); these sum to the meal totals, so the client can rescale a dish by an
   edited portion (linear in grams) without re-querying USDA. No DB write yet — the user
   reviews (the LogMeal UI highlights matched dishes vs. per-ingredient outcomes, and lets
   them edit each dish's portion to recalculate), then logs.

**`POST /api/meals/log` and `/log-group`** — `meal_service` writes the `Meal` (+ `Macros`,
`Micros`) rows; grouped meals share a `group_id`. Temp images are kept or purged per request.

**`GET /api/meals/timeline`** — `meal_service.build_timeline` pages the meals and collapses
rows sharing a `group_id` into a `MealGroupSummary` (summed via `core.nutrients` helpers);
ungrouped rows become `MealSummary`. A discriminated union (`item_type`) lets the frontend
pick the right card. **Route order matters**: `/timeline` and `/group/{id}` are declared
before `/{meal_id}` so they aren't swallowed by the catch-all.

**`GET /api/nutrition/daily | /monthly`** — `summary_service` aggregates a profile's meals
over a date range / month into totals + (monthly) per-day breakdown and averages.

---

## Data model

```
Profile 1──* Meal 1──1 Macros          AppConfig(key, value)   # API keys, vision provider/model,
                  └──1 Micros            food_cache(query, ...)  # USDA per-100g cache (per CACHE_VERSION)
```

- `Meal` carries an optional `group_id` (multi-photo sessions) and `image_path`.
- `Macros` (7 fields) and `Micros` (17 fields) are 1:1 with a meal. Their column names
  are mirrored exactly by `core.nutrients.MACRO_KEYS` / `MICRO_KEYS`.
- `app_config` is a simple key/value table; all access goes through `core.config`.
- `food_cache` is the USDA lookup cache (per-100g profiles **and** miss sentinels for
  negative caching); the lifespan purges it when `CACHE_VERSION` (in
  `services/nutrition_data/config.py`) changes, so improved matching/aliases aren't masked
  by stale rows (incl. stale cached misses).

---

## Conventions

- **Single sources of truth.** Nutrient field lists → `core.nutrients`. Config access &
  defaults → `core.config`. Don't re-declare these elsewhere.
- **Keep routers thin.** New endpoint logic goes in a service; the router just wires it.
- **Dish aliases are curated empirically.** Add a dish to `DISH_ALIASES` only after
  confirming it matches in FNDDS via `python check_aliases.py <key>` (it audits dishes too).
  An unverified dish is harmless but wasteful — it just falls back to decomposition.
- **`core` depends on nothing above it.** If `core` needs something from `services`,
  the dependency is pointing the wrong way — move the shared piece down into `core`. (The
  lifespan's *startup* call into `vision_service.reload_clients` is a deliberate exception,
  done via a local import so it isn't a module-load dependency.)
- **Expensive clients are built once and reused, never per request.** The vision provider
  clients (`vision_service`) are built in the lifespan and rebuilt only when a key/model
  changes (`PUT /api/config` → `reload_clients`); USDA shares a `requests.Session` and a
  thread pool; the DB engine is pooled. This is FastAPI's documented shared-resource pattern.
- **External calls are off the event loop** (`asyncio.to_thread`) and **time-bounded**
  (vision: 15s + one retry; USDA: `(3.05s connect, 10s read)` + one retry on transient
  Timeout/ConnectionError). Rate limits surface as HTTP 429, never silent zeros.
- **`MOCK_GEMINI=1`** short-circuits *both* stages (canned dish list + canned totals, no
  network). The name is historical — it is provider-agnostic, not Gemini-only.
- **Logging** is timestamped and thread-named (`core.logging_config`); parallel USDA
  workers log under `usda-lookup_*` so they're distinguishable from the request thread.

---

## Config & secrets

API keys (`groq_api_key`, `gemini_api_key`, `usda_api_key`) and the vision
provider/model live in the `app_config` table, editable via Settings (`PUT /api/config`,
which also calls `vision_service.reload_clients` so the change takes effect immediately)
or seeded from env vars (`GROQ_API_KEY` / `GEMINI_API_KEY` / `USDA_API_KEY`) on first
launch by `core.config.seed_defaults`. `GET /api/config` reports only whether each key
is set — it never returns key values. CORS is locked down by default (same-origin serving);
set `CORS_ORIGINS` (comma-separated) only if a separate origin must reach the API.
`GET /api/health` returns `{"status":"ok"}`; a global exception handler logs unhandled
errors and returns a clean 500.

---

## Tests

`backend/tests/` — stdlib `unittest`, no network (USDA calls via the shared
`usda_service._SESSION.post` are stubbed; the cache points at a temp DB so the real
`nutrition.db` is untouched). Run from `backend/`:

```
python -m unittest discover -s tests
```

`test_vision_service.py` covers Stage-1 dish parsing and `reload_clients`;
`test_usda_service.py` covers aliasing, matching, the cache (incl. negative caching),
the lookup cap, the curated dish-lookup gate, transient-timeout retries, and rate-limit
propagation.
