# NutriAI

A fully local, AI-powered nutrition tracker for desktop and mobile browsers on the same WiFi.
Photograph a meal → get an accurate macro/micro breakdown → track nutrition over time. Perception
is done by a **vision LLM**; the **nutrient numbers come from USDA FoodData Central** (the LLM
hallucinated nutrients when asked to do both — see [Two-stage pipeline](#two-stage-pipeline)).

This file is the **single source of truth** for the project — stack, how to run, structure,
request flows, and conventions. (Session-by-session history lives in `git log`.)

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14 + FastAPI + SQLAlchemy |
| Database | SQLite (`backend/nutrition.db`, WAL) — persists across restarts |
| AI vision | **Provider-configurable.** Default **Groq · Llama 4 Scout** (`meta-llama/llama-4-scout-17b-16e-instruct`); Gemini/Gemma or **local Ollama** (`qwen3-vl:4b-instruct`) selectable. Identifies dishes/ingredients only. |
| Nutrient data | **USDA FoodData Central** API (`usda_api_key`, default `DEMO_KEY`) — real macros/micros, cached in SQLite `food_cache`. |
| Frontend | React 18 + Tailwind CSS (Vite build) |
| Serving | FastAPI serves the React `dist/` as static files on port 8000 |

> **Why Groq?** On this Google free-tier account every usable Gemini Flash model is capped at
> ~20 requests/day, and `gemma-4-31b-it` has only 383 TPM (can't fit one image → 504s). Groq's
> free tier gives ~1,000 RPD / 6K TPM / 30 RPM plus the fastest inference. Each provider uses its
> own key (`groq_api_key` / `gemini_api_key`); set the model in Settings.

---

## How to run

```powershell
# Dev mode — hot reload (Vite on :8000, FastAPI on :8001):
.\start.ps1 -Dev
$env:MOCK_GEMINI = "1"; .\start.ps1 -Dev      # skip all real model calls (canned data)

# Production mode — build the React app, then serve it via FastAPI on :8000:
.\start.ps1
.\start.ps1 -SkipBuild                         # backend-only changes (serves existing build)
$env:MOCK_GEMINI = "1"; .\start.ps1

# Git Bash equivalents:
bash start.sh --dev   |   bash start.sh   |   bash start.sh --skip-build
```

- Desktop: `http://localhost:8000` (dev and production).
- Mobile (same WiFi): run `ipconfig`, find your IPv4 address, open `http://<your-ip>:8000`.
- Dev mode: Vite owns :8000 and proxies `/api/*` → FastAPI on :8001; `.jsx`/`.css` hot-reload and
  the backend runs with `--reload`.
- If PowerShell blocks the script: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`.

> **Always run `.\start.ps1` (full rebuild) after any frontend change** — `-SkipBuild` serves
> stale JS.

**First-time AI setup:** get a free Groq key at <https://console.groq.com/keys> (no card) and a
free USDA key at <https://fdc.nal.usda.gov/api-key-signup>, then paste them into **Settings**.
Optionally seed via `GROQ_API_KEY` / `GEMINI_API_KEY` / `USDA_API_KEY` env vars before first launch.
`DEMO_KEY` works out-of-box at a low limit (30/hr + 50/day — a couple of meals exhausts it).

**Local vision (no key, no quota):** install [Ollama](https://ollama.com/download), run
`ollama pull qwen3-vl:4b-instruct` (3.3 GB; ~4 GB VRAM — fits an 8 GB GPU comfortably), then pick
**Ollama · Qwen3-VL 4B** in Settings. The daemon serves on `http://localhost:11434`
(override with `OLLAMA_HOST`). The first analysis after startup is slower while the model loads
into VRAM; subsequent calls take a few seconds.

**Freeing the GPU / stopping Ollama:**

```powershell
ollama ps                      # what's loaded right now (PROCESSOR shows GPU vs CPU)
ollama stop qwen3-vl:4b-instruct   # unload the model from VRAM (daemon keeps running)
```

- Ollama auto-unloads an idle model after ~5 min; set `OLLAMA_KEEP_ALIVE` to change that
  (`0` = unload immediately after each call, `-1` = keep resident — avoids the cold-load wait).
- To stop the **daemon** too: quit **Ollama** from the Windows system tray, or
  `Stop-Process -Name ollama -Force` (also `ollama app` on some installs). It restarts on next
  login unless you disable it in Windows **Settings → Apps → Startup**.

**Starting it again:**

```powershell
# If you only stopped the model (daemon still running): just analyze a meal — it reloads
# automatically. To preload it now and skip the cold-load wait on the first photo:
ollama run qwen3-vl:4b-instruct "ok"   # warms the model into VRAM, then exits

# If you stopped the daemon: relaunch the Ollama app from the Start menu (it runs the
# server in the tray), or start it headless:
ollama serve                           # serves on http://localhost:11434
```

- Confirm it's back with `ollama ps` — `PROCESSOR` should read `100% GPU`. No need to restart
  NutriAI; the next **Analyze** picks it up.

---

## Two-stage pipeline

The core design splits **perception** (LLM) from **facts** (USDA):

```
 photo ─> [Stage 1: vision_service] ─dishes(+ingredient fallback)─> [Stage 2: usda_service] ─> macros+micros ─> DB
           (Groq / Gemini / Ollama)                                   dish-first, else decompose
                                                                      (USDA FNDDS + SQLite cache)
```

- **Stage 1 — perception** (`vision_service`): the vision model returns a compact list of
  **dishes**, each with a portion weight and a fallback base-ingredient breakdown — no nutrients.
- **Stage 2 — nutrient lookup** (`usda_service`) is **dish-first**: it looks the whole dish up in
  USDA's **FNDDS** database (which carries composite dishes, including Indian ones like
  idli/dosa/sambar) and only **decomposes into base ingredients when no dish-level match exists**.
  A whole "idli" entry scaled by portion weight is far more accurate than summing mis-stated
  "cooked rice + cooked lentils"; decomposition is the safety net for anything FNDDS lacks.

Per-100g nutrients are scaled by `grams/100` and summed into a **7-macro + 17-micro** schema.
Each dish also carries its own nutrient subtotal (Σ per-dish = meal totals), so the LogMeal review
step can rescale a dish by an edited portion **client-side** (linear in grams) without re-querying
USDA.

---

## Layered backend

FastAPI + SQLAlchemy + SQLite, in four layers. **Dependencies point one way:
`routers → services → core → (models, schemas)`.** `core` never imports from `services`/`routers`;
`schemas` is a leaf.

```
backend/
├── main.py                  # entrypoint: load env, configure logging, assemble routers, serve frontend
│
├── core/                    # infrastructure & cross-cutting concerns (no business logic)
│   ├── database.py          #   SQLAlchemy engine (pool_pre_ping + SQLite WAL/busy_timeout pragmas), SessionLocal, Base, get_db
│   ├── logging_config.py    #   configure_logging(): one timestamped, thread-named formatter for app + uvicorn
│   ├── config.py            #   app_config table access + vision defaults + filesystem paths (UPLOADS_DIR/DIST_DIR/BACKEND_DIR) + CACHE_VERSION
│   ├── nutrients.py         #   SINGLE SOURCE for the 7-macro/17-micro schema + to_*_data / sum_* helpers
│   └── lifespan.py          #   startup/shutdown: create tables, migrate, prep cache, seed config, build vision clients
│
├── models.py                # SQLAlchemy ORM: Profile, Meal (with group_id), Macros, Micros, AppConfig
├── schemas.py               # Pydantic request/response models (leaf): AnalyzeResponse, DishBreakdown, IngredientBreakdown, ...
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
        ├── config.py        #     USDA endpoint + tuning (timeouts/retries) + DISH_DATA_TYPES + USDA_MAX_LOOKUPS
        ├── aliases.py       #     FOOD_ALIASES + DISH_ALIASES + word-set vocabularies for name normalization
        ├── nutrient_map.py  #     USDA nutrientId -> our schema key
        └── mock.py          #     canned totals for MOCK_GEMINI mode
```

### Layer responsibilities

- **`core/`** — infrastructure only: DB session, logging, the nutrient schema, config-table
  access, the FastAPI lifespan. No request handling, no domain rules.
  - `core/nutrients.py` is the **single source of truth** for `MACRO_KEYS` / `MICRO_KEYS` and the
    `to_macros_data` / `to_micros_data` / `sum_macros` / `sum_micros` helpers.
  - `core/config.py` is the **single home for `app_config` access** (`get_value`, `set_value`,
    `get_api_key`, `get_vision_config`, `get_usda_key`, `seed_defaults`), plus the vision defaults
    (`DEFAULT_PROVIDER`/`DEFAULT_MODEL`) and path constants (`UPLOADS_DIR`, `DIST_DIR`, `BACKEND_DIR`).
- **`models.py` / `schemas.py`** — the persistence shape vs. the wire shape, kept separate.
  `schemas.py` imports nothing from the app, so `core.nutrients` can depend on it without a cycle.
- **`routers/`** — one file per resource; each handler is a thin wrapper (read request → call a
  service → return). Routers own only HTTP concerns.
- **`services/`** — all domain logic: where `db` is used, queries run, external APIs are called,
  and results are assembled into schema objects.

### Frontend (`frontend/src/`)

```
App.jsx · main.jsx · context/ProfileContext.jsx · api/client.js (45s axios timeout)
pages/      ProfileSelect · Home · LogMeal · Timeline · Monthly · Settings
components/  layout/ (Layout, TopBar, BottomNav)
            meal/   (MealCard, GroupedMealCard, MealDetailModal, MacroRing, MicroGrid)
            summary/(MacroProgressBar)   shared/(Spinner, Toast, EmptyState, ConfirmModal)
```

`LogMeal.jsx` is the heart: multi-photo upload (staged, no call) → optional AI hint → Analyze →
review (editable per-dish portions rescale client-side) → log. `uid()` (Math.random) replaces
`crypto.randomUUID` for browser compatibility. All destructive actions use the shared
`ConfirmModal` — never a browser `confirm()`.

In the **Home** and **Timeline** feeds a grouped multi-photo session renders with
`GroupedMealCard` — a layered "deck" look (two offset shadow layers behind the card) plus a
`🍱 Session · N items` badge — so it's distinguishable at a glance from a flat single
`MealCard`. Which card to render is driven by the `item_type` discriminator on each feed row.

---

## Request flows

**`POST /api/meals/analyze`** (the heart of the app)
1. `routers/meals.py` reads the image bytes and calls `meal_service.analyze_image`.
2. `meal_service` reads the configured provider/key (`core.config`), saves a temp image, and runs
   **Stage 1** — `vision_service.analyze_meal_image` in a worker thread (`asyncio.to_thread`, so
   the event loop never blocks) → a list of dishes (portion weight + fallback ingredient breakdown).
3. It runs **Stage 2** — `usda_service.nutrients_for_meal` (also off-thread), **dish-first**: a
   whole-dish lookup is attempted only for **curated** dishes (`_normalize(name) in DISH_ALIASES`);
   un-curated names skip the speculative call and decompose via `_sum_ingredients` (alias →
   head-noun gate → scale → sum). Lookups run in parallel on a **shared module-level
   `ThreadPoolExecutor`** over a shared `requests.Session`; a per-meal uncached-lookup budget
   (`USDA_MAX_LOOKUPS`) bounds API usage. Positive matches **and definitive misses** are cached
   (negative caching); transient timeouts are retried, not cached.
4. The `AnalyzeResponse` is a **dish-grouped breakdown**:
   `dishes: [{name, grams, matched, macros, micros, ingredients:[{food, grams, status}]}]` where
   `status ∈ matched | unmatched | skipped | not_looked_up`, plus aggregate `unmatched`/`skipped`
   name lists. No DB write yet — the user reviews, optionally edits portions, then logs.

**`POST /api/meals/log` and `/log-group`** — `meal_service` writes the `Meal` (+ `Macros`,
`Micros`) rows; grouped multi-photo sessions share a `group_id`. Temp images are kept or purged
per request.

**`GET /api/meals/timeline`** — `meal_service.build_timeline` pages the meals and collapses rows
sharing a `group_id` into a `MealGroupSummary` (summed via `core.nutrients` helpers); ungrouped
rows become `MealSummary`. A discriminated union (`item_type`) tells the frontend which card to
render. **Route order matters:** `/timeline` and `/group/{id}` are declared before `/{meal_id}` so
the catch-all doesn't swallow them.

**`GET /api/nutrition/daily | /monthly`** — `summary_service` aggregates a profile's meals over a
date range / month into totals + (monthly) per-day breakdown and averages.

---

## Data model

```
Profile 1──* Meal 1──1 Macros          AppConfig(key, value)   # API keys, vision provider/model
                  └──1 Micros           food_cache(query, ...)  # USDA per-100g cache (per CACHE_VERSION)
```

- `Meal` carries an optional `group_id` (multi-photo sessions) and `image_path`.
- `Macros` (7 fields) and `Micros` (17 fields) are 1:1 with a meal; their columns mirror
  `core.nutrients.MACRO_KEYS` / `MICRO_KEYS` exactly.
- `app_config` is a key/value table; all access goes through `core.config`.
- `food_cache` holds per-100g profiles **and** miss sentinels (negative caching); the lifespan
  purges it when `CACHE_VERSION` (in `core/config.py`) changes, so improved matching/aliases
  aren't masked by stale rows.

**Timezone handling:** the backend stores naive UTC strings. The frontend appends `"Z"` before
`new Date(...)` so local time renders correctly; `Home.jsx` sends local-midnight `date_from`/
`date_to` as UTC ISO and the daily query filters by range (not `func.date()`), so meals near
midnight land on the right day regardless of timezone.

---

## Conventions

- **Single sources of truth.** Nutrient field lists → `core.nutrients`. Config access & defaults →
  `core.config`. Don't re-declare these elsewhere.
- **Keep routers thin.** New endpoint logic goes in a service; the router just wires it. Routes set
  `response_model` / `status_code` / `summary` explicitly.
- **Validate at the edge with Pydantic.** Request schemas use `StrEnum`s (`MealType`, `Confidence`,
  `VisionProvider`, `IngredientStatus`) and `Field` constraints (PIN `^\d{4}$`, `ge=0` on
  nutrients/grams). LLM-derived `meal_type`/`confidence` are normalized in
  `vision_service._parse_compact` **before** the strict `AnalyzeResponse`, so a surprise model
  output can't 500.
- **DB identifiers use a naming convention.** `Base.metadata` (`core.database`) sets a
  `naming_convention` so indexes/FKs/PKs get deterministic names.
- **Dish aliases are curated empirically.** Add to `DISH_ALIASES` only after confirming an FNDDS
  match via `python check_aliases.py <key>`. An unverified dish is harmless — it just falls back to
  decomposition.
- **`core` depends on nothing above it.** If `core` needs something from `services`, move the
  shared piece down into `core`. (The lifespan's startup call into `vision_service.reload_clients`
  is a deliberate exception via a local import.)
- **Expensive clients are built once and reused, never per request.** Vision provider clients are
  built in the lifespan and rebuilt only on a key/model change (`PUT /api/config` →
  `reload_clients`); USDA shares a `requests.Session` and a thread pool; the DB engine is pooled.
- **External calls are off the event loop** (`asyncio.to_thread`) and **time-bounded** (vision:
  Groq/Gemini 15s, local Ollama 120s — each + one retry; USDA: `(3.05s connect, 10s read)` +
  one retry on a transient `Timeout`/`ConnectionError` **or** a transient HTTP status
  (`USDA_TRANSIENT_STATUS` = 404/5xx — USDA's gateway intermittently serves an HTML error page
  instead of JSON)). Rate limits (429/403) surface as HTTP 429 and fail fast, never silent zeros.
- **`MOCK_GEMINI=1`** short-circuits *both* stages (canned dish list + canned totals, no network).
  The name is historical — it is provider-agnostic, not Gemini-only.
- **Logging** is timestamped and thread-named (`core.logging_config`); parallel USDA workers log
  under `usda-lookup_*` so they're distinguishable from the request thread.

---

## Config & secrets

API keys (`groq_api_key`, `gemini_api_key`, `usda_api_key`) and the vision provider/model live in
the `app_config` table, editable via Settings (`PUT /api/config`, which also calls
`vision_service.reload_clients` so the change takes effect immediately) or seeded from env vars on
first launch by `core.config.seed_defaults`. `GET /api/config` reports only whether each key is
set — never the values. CORS is locked down by default (same-origin serving); set `CORS_ORIGINS`
(comma-separated) only if a separate origin must reach the API. `GET /api/health` returns
`{"status":"ok"}`; a global exception handler logs unhandled errors and returns a clean 500.
Interactive docs (`/docs`, `/redoc`, `/openapi.json`) are on by default; set `APP_ENV=production`
to disable them for a shared deployment.

---

## API quick reference

```
GET    /api/profiles              List all profiles
POST   /api/profiles              Create profile {name, pin, avatar_color}
POST   /api/profiles/verify       Verify {profile_id, pin} → profile or 401 (scoped to profile_id)
DELETE /api/profiles/{id}         Soft-delete profile

GET    /api/health                {status:"ok"} — liveness check
POST   /api/meals/analyze         Image → AI analysis (no DB write); returns dishes[] breakdown
POST   /api/meals/log             Save a single analyzed meal
POST   /api/meals/log-group       Save {group_id, meals:[...]} as a grouped session
GET    /api/meals/timeline        ?profile_id&page&limit — paginated, grouped by group_id
GET    /api/meals/group/{id}      Full MealGroupSummary (total_macros + total_micros)
DELETE /api/meals/group/{id}      Delete all meals in a group
GET    /api/meals/{id}            Full meal detail (macros + micros)
PATCH  /api/meals/{id}            Update a meal
DELETE /api/meals/{id}            Delete a meal

GET    /api/nutrition/daily       ?profile_id&date_from&date_to — day totals
GET    /api/nutrition/monthly     ?profile_id&year&month — monthly breakdown + averages

GET    /api/config                {gemini_api_key_set, groq_api_key_set, usda_api_key_set, vision_provider, vision_model}
PUT    /api/config                Save any of {gemini_api_key, groq_api_key, usda_api_key, vision_provider, vision_model}
```

Interactive docs: `http://localhost:8000/docs`. **Group routes are declared before `/{meal_id}`**
to avoid FastAPI routing conflicts.

### Daily reference targets (UI progress bars)

| Calories | Protein | Carbs | Fat |
|---|---|---|---|
| 2000 kcal | 150 g | 250 g | 65 g |

Micros are shown as raw values (no goal bars) in a collapsible `MicroGrid`.

---

## Tests

`backend/tests/` — stdlib `unittest`, **no network** (USDA calls via `usda_service._SESSION.post`
are stubbed; the cache points at a temp DB so the real `nutrition.db` is untouched). Run from
`backend/`:

```
python -m unittest discover -s tests
```

`test_vision_service.py` covers Stage-1 dish parsing and `reload_clients`; `test_usda_service.py`
covers aliasing, matching, the cache (incl. negative caching), the lookup cap, the curated
dish-lookup gate, transient-timeout retries, and rate-limit propagation.

**Linting:** Ruff is configured in `backend/pyproject.toml` (runtime deps stay in
`requirements.txt`). Install with `python -m pip install ruff`, then from `backend/`:
`ruff check` and `ruff format`.

---

## Utility scripts

- `backend/check_aliases.py` — audits every `FOOD_ALIASES`/`DISH_ALIASES` entry against the **real**
  USDA API through the production matching path (read-only, bypasses cache), printing each chosen
  match or `UNMATCHED`. Run from `backend/`: `python check_aliases.py <usda_key>` (or `USDA_API_KEY`
  env / `backend/.env`). Use it after editing aliases.
- `check_gemini_limits.py` (project root) — lists available Gemini models with token limits and
  tests an API key. Run: `python check_gemini_limits.py <api_key>`.

---

## What's not built yet

- Per-*ingredient* gram editing and swapping a matched food (dish-portion editing already covers
  the dominant error; this is deliberately out of scope for now).
- Single-item LLM nutrient fallback for `unmatched` foods (currently warn-only by design);
  Open Food Facts barcode path; IFCT 2017 for dish-level Indian accuracy.
- Custom per-profile calorie/macro goals; manual edit of logged nutrition values.
- Keep-image toggle in the LogMeal UI (backend already supports `keep_image: true` on `/meals/log`).
- Data export (CSV / PDF); dark mode; direct camera-open on mobile.
```
