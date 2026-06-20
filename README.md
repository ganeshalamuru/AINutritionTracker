# NutriAI

An AI-powered nutrition tracker for desktop and mobile browsers. Photograph a meal → get an
accurate macro/micro breakdown → track nutrition over time. Perception is done by a **vision LLM**;
the **nutrient numbers come from USDA FoodData Central** (the LLM hallucinated nutrients when asked
to do both — see [Two-stage pipeline](#two-stage-pipeline)).

> **Deployment pivot (in progress).** NutriAI began as a *fully local* app (run on your machine,
> reachable from phones on the same WiFi) and is **pivoting toward deployment as a hosted Linux
> container** — see [Docker & deployment](#docker--deployment). It still runs fully locally for dev;
> development happens on Windows while the deploy target is a Linux container, so keep changes
> portable (no hardcoded Windows-only paths/commands or local-only runtime assumptions).

This file is the **single source of truth** for the project — stack, how to run, structure,
request flows, and conventions. (Session-by-session history lives in `git log`.)

---

## Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14 + FastAPI + SQLAlchemy (deps managed with **uv**) |
| Database | SQLite (`backend/nutrition.db`, WAL) — persists across restarts |
| AI vision | **Provider-configurable.** Default **Groq · Llama 4 Scout** (`meta-llama/llama-4-scout-17b-16e-instruct`); Gemini/Gemma or **local Ollama** (`qwen3-vl:4b-instruct` / `qwen3-vl:8b-instruct`) selectable. Identifies dishes/ingredients only. |
| Nutrient data | **USDA FoodData Central**, two interchangeable backends (Settings → *Nutrition Data Source*, `nutrition_source`): **offline** (default) — local SQLite **FTS5** index `backend/usda_local.db` built by `build_usda_db.py`, no network/limits; **online** — the FDC API (`usda_api_key`, default `DEMO_KEY`). Both feed the same matching code; results cached in SQLite `food_cache`. |
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

**Python dependencies use [uv](https://docs.astral.sh/uv/).** `backend/pyproject.toml` declares the
runtime + dev (`ruff`, `pytest`) dependencies and `backend/uv.lock` pins the full graph. The start
scripts prefer uv (`uv sync` → `uv run uvicorn …`) and **fall back to `pip install -r
requirements.txt` when uv isn't on PATH**, so the app still starts without it. `requirements.txt` is
a generated export of the lock (`uv export`), kept for that fallback and pip-only environments —
**don't hand-edit it**; change `pyproject.toml` then run `uv lock` + `uv export --no-hashes --no-dev
-o requirements.txt`. Work in the backend directly with `uv run` (e.g. `uv run uvicorn main:app`).

**First-time AI setup:** get a free Groq key at <https://console.groq.com/keys> (no card) and
paste it into **Settings**. Optionally seed via `GROQ_API_KEY` / `GEMINI_API_KEY` env vars before
first launch.

**Nutrient data (offline by default):** build the local USDA search index once —
```powershell
cd backend; python build_usda_db.py    # usda_data/ CSVs -> backend/usda_local.db (~11 MB, gitignored)
```
This reads the FoodData Central CSV export under `usda_data/` and is the default Stage-2 backend
(no key, no network). To use the live API instead, switch **Settings → Nutrition Data Source** to
*USDA API* and add a free USDA key (<https://fdc.nal.usda.gov/api-key-signup>); `DEMO_KEY` works
out-of-box at a low limit (30/hr + 50/day). Seed the choice via the `NUTRITION_SOURCE`
(`offline`|`online`) / `USDA_API_KEY` env vars before first launch.

**Local vision (no key, no quota):** install [Ollama](https://ollama.com/download), pull a
Qwen3-VL model, then pick **Ollama** as the provider and the model in Settings (provider and
model are separate dropdowns). Two local models are offered:

- `ollama pull qwen3-vl:4b-instruct` (3.3 GB) — **fits an 8 GB GPU fully and is fast**
  (a few seconds per photo). Good default for local use.
- `ollama pull qwen3-vl:8b-instruct` (~6 GB) — **more accurate** at identifying dishes
  (esp. Indian dishes), but on an 8 GB GPU it **only partly fits** (Ollama offloads ~25–35%
  of layers to CPU → ~40 s per photo). Comfortable/fast on a 12 GB+ GPU.

The daemon serves on `http://localhost:11434` (override with `OLLAMA_HOST`). The first
analysis after startup is slower while the model loads into VRAM.

> **VRAM note.** We pin the local context window to `num_ctx=4096` (Ollama's default-ish —
> plenty for one image + a short prompt). Don't raise it hoping to "fit more context": a
> larger window only enlarges the KV-cache reservation and pushes *more* model layers onto
> the CPU on a small GPU. Check the split with `ollama ps` — `PROCESSOR` shows GPU vs CPU.
> Override `OLLAMA_NUM_CTX` only if a very high-res photo ever truncates.

**Freeing the GPU / stopping Ollama:**

```powershell
ollama ps                      # what's loaded right now (PROCESSOR shows GPU vs CPU)
ollama stop qwen3-vl:8b-instruct   # unload the model from VRAM (daemon keeps running)
```

(Substitute `qwen3-vl:4b-instruct` in any of these commands when running the 4B.)

- Ollama auto-unloads an idle model after ~5 min; set `OLLAMA_KEEP_ALIVE` to change that
  (`0` = unload immediately after each call, `-1` = keep resident — avoids the cold-load wait).
- To stop the **daemon** too: quit **Ollama** from the Windows system tray, or
  `Stop-Process -Name ollama -Force` (also `ollama app` on some installs). It restarts on next
  login unless you disable it in Windows **Settings → Apps → Startup**.

**Starting it again:**

```powershell
# If you only stopped the model (daemon still running): just analyze a meal — it reloads
# automatically. To preload it now and skip the cold-load wait on the first photo:
ollama run qwen3-vl:8b-instruct "ok"   # warms the model into VRAM, then exits

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
 photo ─> [Stage 1: vision_service] ─dishes(+ingredient fallback)─> [Stage 2: usda_service] ─> nutrients ─> DB
           (Groq / Gemini / Ollama)                                   dish-first, else decompose
                                                          (USDA FNDDS via offline FTS5 or online API + cache)
```

- **Stage 1 — perception** (`vision_service`): the vision model returns a JSON list of
  **dishes**, each with a portion weight and a fallback base-ingredient breakdown — no nutrients.
  The prompt (`NUTRITION_PROMPT`) asks for an explicit, readable schema:

  ```json
  {"meal_name":"Name","type":"breakfast|lunch|dinner|snack","confidence":"high|medium|low",
   "dishes":[{"name":"dish name","total_grams":0,
              "components":[{"item":"ingredient/component","usda_name":"generic name","grams":0}]}]}
  ```

  `components` is the 2–4 primary macro-ingredient fallback (used only when Stage 2 finds no
  dish-level match); the prompt instructs the model to list **only components it can actually see**
  and not guess ingredients that aren't visible (it otherwise hallucinates expected toppings — e.g.
  a phantom sausage on a chicken pizza). Each component also carries a **`usda_name`** — a generic,
  common English name a nutrition DB would list (`jeera rice` → `cooked white rice`, `bhindi` →
  `okra`). This pushes the open-vocabulary normalization to the stage that already understands food
  language (the vision LLM); Stage 2 searches `usda_name` while the visible `item` is kept for
  display/status. It's a *suggestion*, not a bypass — the query still flows through the curated
  alias rewrite + head-noun gate (so a bad `usda_name` is no worse than today, and curated aliases
  stay authoritative). `vision_service._parse_compact` remaps this to the internal shape
  (`meal_type`/`dishes:[{name, grams, items:[{food, grams, usda_name}]}]`), defaulting `usda_name`
  to `food` when the model omits it, and coerces `type`/`confidence` to the known vocabularies
  before the strict `AnalyzeResponse`. All three providers reach the model through their official
  client (Groq / Gemini / **`ollama`**) in **plain JSON mode** (`format="json"` / `response_format`)
  — the prompt alone carries the shape, and the current `qwen3-vl` models keep the wrapper without a
  hard JSON schema (verified on the 4B and 8B).
- **Stage 2 — nutrient lookup** (`usda_service`) is **dish-first**: it looks the whole dish up in
  USDA's **FNDDS** database (which carries composite dishes, including Indian ones like
  idli/dosa/sambar — and sweets such as ladoo/barfi natively, or via a close proxy where FNDDS
  lacks the exact name, e.g. `gulab jamun → jelly doughnut`, `jalebi → funnel cake`) and only
  **decomposes into base ingredients when no dish-level match exists**. A whole "idli" entry scaled
  by portion weight is far more accurate than summing mis-stated "cooked rice + cooked lentils";
  decomposition is the safety net for anything FNDDS lacks. A proxy is added only when it's
  genuinely close on calories — dishes with no honest match (e.g. rasgulla, halwa) stay unmatched
  rather than report a wrong number.
- **Two search backends, one matching pipeline.** The single seam is `usda_service._search_usda`,
  which returns USDA-shaped candidates either from the **offline** local FTS5 index
  (`usda_local_search`, default) or the **online** FDC API. Everything downstream — alias/simplify
  query rewriting, the `_pick_best` head-noun gate + ranking, `_extract_per_100g`, and the
  `food_cache` (offline keys namespaced `local::` so the two backends never collide) — is shared
  unchanged. Switch backends in Settings; no restart.

Per-100g nutrients are scaled by `grams/100` and summed into a single flat **33-nutrient**
"standard nutrients" schema. The backend draws **no macro/micro line** — it stores and transports
one nutrient bag (`core.nutrients.NUTRIENT_KEYS`); the macro / micro / fat-breakdown grouping is a
**display-only** concern made in the frontend (the headline macros in the ring, vitamins/minerals
in `MicroGrid`, and the fat breakdown — saturated/mono/poly fat, cholesterol, omega-3 EPA+DHA —
picked out under Fat). Each dish also carries its own nutrient subtotal (Σ per-dish = meal totals), and each **decomposed**
dish's ingredients carry their *own* subtotals too (Σ per-ingredient = that dish's subtotal), so the
LogMeal review step can rescale a dish — or an individual ingredient — by an edited portion
**client-side** (linear in grams) without re-querying USDA.

---

## Layered backend

FastAPI + SQLAlchemy + SQLite, in four layers. **Dependencies point one way:
`routers → services → core → (models, schemas)`.** `core` never imports from `services`/`routers`;
`schemas` is a leaf.

```
backend/
├── main.py                  # entrypoint: load env, configure logging, optional Sentry/Prometheus, request-context/access-log middleware, health/readiness, assemble routers, serve frontend
│
├── build_usda_db.py         # one-time ETL: usda_data/ CSVs -> backend/usda_local.db (offline FTS5 search index)
│
├── core/                    # infrastructure & cross-cutting concerns (no business logic)
│   ├── database.py          #   SQLAlchemy engine (pool_pre_ping + SQLite WAL/busy_timeout pragmas), SessionLocal, Base, get_db
│   ├── logging_config.py    #   configure_logging(): one timestamped, thread-named, request-correlated formatter (app + uvicorn); LOG_LEVEL env
│   ├── request_context.py   #   per-request trace id + user id (contextvars) + log-record factory that stamps them onto every line
│   ├── config.py            #   app_config table access + vision/nutrition_source defaults + filesystem paths (UPLOADS_DIR/DIST_DIR/BACKEND_DIR) + CACHE_VERSION
│   ├── nutrients.py         #   SINGLE SOURCE for the flat 33-nutrient schema + to_nutrients_data / sum_nutrients helpers
│   ├── security.py          #   bcrypt password hash/verify + PyJWT access/refresh mint/decode + JWT_SECRET handling
│   ├── auth.py              #   FastAPI authz dependencies: get_current_user / get_current_admin (the single authz chokepoint)
│   └── lifespan.py          #   startup/shutdown: rename legacy schema (profiles->users) + create tables, migrate, prep cache, seed config, build vision + USDA clients
│
├── models.py                # SQLAlchemy ORM: User (table "users"), RefreshToken, Meal (with group_id), Nutrients (flat 33-field), AppConfig
├── schemas.py               # Pydantic request/response models (leaf): AnalyzeResponse, DishBreakdown, IngredientBreakdown, ...
│
├── routers/                 # thin HTTP layer — parse request, call a service, return result
│   ├── auth.py              #   /api/auth (register, login, refresh, logout, me, change-password)
│   ├── users.py             #   /api/users (own goal via /me; admin-only list/role/active/reset-password)
│   ├── meals.py             #   /api/meals ...   (analyze, log, timeline, group, detail) — owner-scoped via the access token
│   ├── nutrition.py         #   /api/nutrition/daily | /monthly — scoped to the authenticated user
│   ├── config.py            #   /api/config (admin-only: GET/PUT keys + vision provider/model + nutrition_source; rebuilds clients on change)
│   ├── foods.py             #   /api/foods (search + get-by-id over usda_local.db; always on; public USDA data)
│   └── admin.py             #   /api/admin (dev-only + admin-only data inspection: tables, food-cache, meals, config, read-only SQL console)
│
└── services/                # business logic — where the work actually happens
    ├── vision_service.py    #   Stage 1: dispatch photo to a vision provider -> dish list (+fallback ingredients); shared clients
    ├── usda_service.py      #   Stage 2: dish-first lookup, matching, SQLite cache (+ negative caching); routes _search_usda to online API or offline index via reload_client
    ├── usda_local_search.py #   Stage 2 offline backend: FTS5 query over usda_local.db -> USDA-shaped candidates (drop-in for _search_usda); also get_food/table_counts for the foods/admin APIs
    ├── admin_query.py        #   guarded read-only SQL for /api/admin/query (SELECT-only validation + mode=ro connection + secret/credential redaction)
    ├── auth_service.py      #   register/login/refresh-rotation/logout/change-password (token + RefreshToken bookkeeping)
    ├── user_service.py      #   own-goal update + admin user management (list/role/active/reset-password)
    ├── meal_service.py      #   analyze orchestration + meal CRUD + timeline/group read models (owner-scoped)
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
  - `core/nutrients.py` is the **single source of truth** for the flat `NUTRIENT_KEYS` list and the
    `to_nutrients_data` / `sum_nutrients` helpers. There is no macro/micro split in the backend —
    that distinction is made only in the frontend display components.
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
App.jsx · main.jsx · constants.js (MEAL_TYPE_COLORS) · context/AuthContext.jsx · context/LogDraftContext.jsx
api/client.js (45s axios timeout; /analyze overrides to 180s for slow local Ollama; attaches Bearer access token + transparent refresh-on-401)
pages/      Login · Register · ChangePassword · Home · LogMeal · Timeline · Monthly · Settings
components/  layout/   (Layout, TopBar, BottomNav, AccountMenu)
            meal/     (MealCard, GroupedMealCard, MealDetailModal, MacroRing, MacroHighlights, MicroGrid, FatBreakdown)
            summary/  (MacroProgressBar)
            settings/ (ApiKeyCard, SettingsSection)   shared/ (Spinner, Toast, EmptyState, ConfirmModal)
hooks/      useMealModal (modal state + per-meal detail cache, shared by Home & Timeline)
utils/      format (logged_at → local time helpers) · nutrients (MACRO_KEYS, emptyNutrients, addNutrients) · uid
```

`LogMeal.jsx` is the heart: multi-photo upload (staged, no call, **up to 4 photos**) → a **per-photo**
AI hint → Analyze → review → log. Each photo carries its own optional hint (sent as `user_note`), and
an analyzed photo can be **re-analyzed** with an edited hint (rebuilds that photo's draft, discarding
its manual edits). More photos can also be staged **after** analysis (an "Add another photo" control
on the review/log step, up to the 4-photo cap) — only the new photo is analyzed, the already-analyzed
ones are left untouched. The in-progress log (staged photos + drafts + hints) lives in `LogDraftContext`
above the router, so it **survives switching tabs and returning** — it's in-memory only (cleared on a
successful log or logout, lost on a full page refresh). On analyze it builds an
editable **draft** from the immutable analysis and re-sums the
meal from it client-side (`draftTotals`), so repeated edits scale from the original baseline and
never compound rounding. Editing granularity follows a deliberate **clean split** by dish type:

- a **matched** dish (counted whole in USDA) is re-portioned as a unit — one editable dish-grams
  field scales its whole subtotal; its detected ingredients were never looked up, so they stay
  read-only chips.
- a **decomposed** dish exposes the *ingredient* as the editable unit — each resolved ingredient has
  its own grams field and Remove/Undo (using the per-ingredient subtotals from Stage 2), and shows
  its **share of the dish (%)**. The dish grams is the live sum of its ingredients **and is itself
  editable**: typing a dish total re-portions every ingredient proportionally (preserving the
  composition split, via a focus-snapshotted largest-remainder distribution so the parts always sum
  to the typed total) — convenient when re-sizing the whole dish is easier than touching each part.
  Editing a single ingredient instead moves only that ingredient, and the dish total follows by the
  same delta. Unmatched/skipped ingredients show but are gram-locked for *direct* edits (no nutrients
  to scale); they still scale with a dish-level edit so the composition stays true.

Either kind can also gain **custom ingredients**: a "+ Add ingredient" control searches the offline
USDA index (`GET /api/foods/search`, debounced type-to-list — richer keyboard-nav autocomplete is
future scope), and the chosen food's per-100g profile (`GET /api/foods/{fdc_id}`) is scaled by the
entered grams and added into that dish. Whole dishes are still **removable** (reversible, with Undo).
The rows lay out as a 3-column grid (name | grams | Remove/Undo) so inputs and actions align in
columns. Logging sends the live macros/micros — not the breakdown — so every edit, removal, and add
persists with **no backend change to the log path**. All destructive actions on *saved* data use the
shared `ConfirmModal` — never a browser `confirm()`.

**Auth (`context/AuthContext.jsx`).** Username + password accounts with JWT access/refresh
tokens. The **access token lives in memory** (inside `api/client.js`) and the **refresh token is
an `HttpOnly` cookie** the browser holds and replays to `/api/auth` — invisible to JavaScript, so
an XSS payload can't exfiltrate the long-lived renewable credential (the access token in memory is
obscured from a standard browser API for the same reason). The cookie is `SameSite=Lax`, scoped to
`Path=/api/auth` (sent only to refresh/logout, not on every call), and `Secure` only when
`APP_ENV=production` — local/LAN runs serve over plain HTTP, where a `Secure` cookie would be
dropped. On boot the app calls `/auth/refresh` (no body — the cookie rides along); on success it
gets a fresh access token and reloads the user, so a reload keeps the session without re-login, and
a 401 simply means "not logged in". `client.js` sends `withCredentials` + the `Authorization:
Bearer` header and, on a 401, transparently refreshes once (single-flight) and retries — dropping
to the login screen only if the refresh itself fails. Token bodies carry only the access token; the
refresh token never appears in a response body. `ProtectedRoute` gates
the app on a valid session and funnels accounts flagged `must_change_password` (admin-resets)
to `ChangePassword`. The TopBar avatar opens **`AccountMenu`** — an
account dropdown (username, **Change password**, **Log out**). API-key/provider settings appear
only for **admin** accounts (the `/api/config` endpoint is admin-only).

**Shared frontend layer (single sources of truth, mirroring the backend convention).** Cross-cutting
pieces live in one place rather than copy-pasted across files: meal-type badge colors in
`constants.js`; date/time formatting in `utils/format.js` (all parse the backend's naive-UTC
`logged_at` via `parseUTC`); nutrient-total shape + summation in `utils/nutrients.js`; `uid()` (Math.random,
**not** `crypto.randomUUID` — browser compatibility) in `utils/uid.js`. The reusable `ApiKeyCard`
backs the three Settings key cards (Groq/Gemini/USDA), and `useMealModal` holds the meal-detail
modal state + cache shared by Home and Timeline (group-modal fetching stays per-page, since Home
caches full group detail while Timeline opens the in-memory group).

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
   `dishes: [{name, grams, matched, nutrients, ingredients:[{food, grams, status, nutrients}]}]` where
   `status ∈ matched | unmatched | skipped | not_looked_up`, plus aggregate `unmatched`/`skipped`
   name lists. No DB write yet — the user reviews, optionally edits portions, then logs.

**`POST /api/meals/log` and `/log-group`** — `meal_service` writes the `Meal` (+ its 1:1
`Nutrients` row); grouped multi-photo sessions share a `group_id`. Temp images are kept or purged
per request.

**`GET /api/meals/timeline`** — `meal_service.build_timeline` pages the meals and collapses rows
sharing a `group_id` into a `MealGroupSummary` (summed via `core.nutrients` helpers); ungrouped
rows become `MealSummary`. A discriminated union (`item_type`) tells the frontend which card to
render. **Route order matters:** `/timeline` and `/group/{id}` are declared before `/{meal_id}` so
the catch-all doesn't swallow them.

**`GET /api/nutrition/daily | /monthly`** — `summary_service` aggregates a user's meals over a
date range / month into totals + (monthly) per-day breakdown and averages.

---

## Data model

```
User 1──* Meal 1──1 Nutrients          AppConfig(key, value)   # API keys, vision provider/model, jwt_secret
User 1──* RefreshToken                  food_cache(query, ...)  # USDA per-100g cache (per CACHE_VERSION)
```

- **`User`** is a user account: `username` (unique login), `name` (display), `password_hash`
  (bcrypt), `role` (`user`|`admin`), `must_change_password`, `avatar_color`, `calorie_goal`,
  `is_active`. The table is `users` and the `Meal` FK column is `user_id`. Login is
  username + password; the **first registered account is the admin**.
- **`RefreshToken`** tracks issued JWT refresh tokens by `jti` so they can be **rotated and
  revoked** server-side (rotation on every `/auth/refresh`; reuse of a rotated token revokes
  the whole chain). The token is delivered to the browser as an `HttpOnly` cookie (never in a
  response body), so JavaScript can't read it. Access tokens are short-lived and stateless
  (never stored), held only in memory by the SPA.
- **Auth model.** Endpoints derive the caller from the `Authorization: Bearer <access>` token
  via the `core.auth` dependencies (`get_current_user` / `get_current_admin`) — never from a
  client-supplied id — so meal/nutrition data is owner-scoped and `/api/config` + `/api/admin`
  are admin-only. A legacy DB whose account table was named `profiles` (with a `meals.profile_id`
  FK) is renamed in place to `users` / `user_id` on startup (idempotent, data-preserving — see
  `core.lifespan._migrate_legacy_schema`).
- `Meal` carries an optional `group_id` (multi-photo sessions) and `image_path`.
- `Nutrients` (33 fields, one flat row) is 1:1 with a meal; its columns mirror
  `core.nutrients.NUTRIENT_KEYS` exactly. (It replaces the former split `Macros`/`Micros` tables;
  the lifespan migrates existing rows into it on startup, leaving the old tables untouched.)
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
  `VisionProvider`, `IngredientStatus`) and `Field` constraints (username
  `^[a-zA-Z0-9_.-]{3,32}$`, password `min_length=8`, `ge=0` on nutrients/grams). LLM-derived
  `meal_type`/`confidence` are normalized in
  `vision_service._parse_compact` **before** the strict `AnalyzeResponse`, so a surprise model
  output can't 500.
- **DB identifiers use a naming convention.** `Base.metadata` (`core.database`) sets a
  `naming_convention` so indexes/FKs/PKs get deterministic names.
- **Aliases are curated empirically.** Add or change entries in `DISH_ALIASES`/`FOOD_ALIASES` only
  after confirming the resolved USDA entry via `python check_aliases.py <key>` — the script prints
  the chosen description + cal/100g, which catches food aliases that *match but resolve to the wrong
  variant* (e.g. a generic "mung beans cooked" landing the **sprouted, stir-fried** ~50 cal entry
  instead of plain boiled ~105). Curate the alias value so the distinctive food word lands **last**
  (the `_food_noun` gate). An unverified dish is harmless — it just falls back to decomposition;
  drop `DISH_ALIASES` entries that don't match FNDDS so they skip the wasted speculative call.
  **Curation is data-driven:** every name that still misses is negative-cached, so
  `python list_misses.py` prints the real worklist — add the worthwhile names to
  `FOOD_ALIASES`/`DISH_ALIASES`, validate with `check_aliases.py`, then bump `CACHE_VERSION`
  (`core/config.py`) so the cached misses are purged and re-resolved.
- **`core` depends on nothing above it.** If `core` needs something from `services`, move the
  shared piece down into `core`. (The lifespan's startup call into `vision_service.init_clients`
  is a deliberate exception via a local import.)
- **Expensive clients are built once and reused; every provider keys per request.**
  `vision_service.init_clients()` builds the **never-rebuilt** pools once at startup (the Groq
  httpx pool + keyless Ollama client); no key is ever baked onto a process-global client, so a
  key/provider/model change needs **no** vision-client rebuild. The orchestrator
  (`analyze_meal_image`) resolves the ready-to-call client per request via
  `_client_for(provider, api_key)` and passes it into the provider function — none of the provider
  functions read a global or re-key. **Groq** injects the key via
  `_groq_client.with_options(api_key=…)` (a copy that reuses the pooled httpx client). **Gemini**
  is built fresh per request as `genai.Client(api_key=…)` and closed afterwards — the newer
  object-scoped `google-genai` SDK keys at the client (no process-global `genai.configure`, no
  cached transport to reset), so there's no Gemini rebuild/reload step at all. **Ollama** is
  keyless. Config stays the single source of truth for the key (`meal_service` fetches it with
  `config.get_api_key`). The USDA client (`usda_service.UsdaClient` — a pooled `requests.Session` +
  a `ThreadPoolExecutor`) is likewise built **once** and reused for the process lifetime; its pools
  are key-independent, so a key change (`reload_client`) only updates the Session's `X-Api-Key`
  header — nothing is rebuilt. The key lives only on that header (lookups take no `api_key` argument
  and it never appears in request URLs/logs). The DB engine is pooled.
- **External calls are off the event loop** (`asyncio.to_thread`) and **time-bounded** (vision:
  Groq/Gemini 15s, local Ollama 120s — each + one retry; USDA: `(3.05s connect, 10s read)` +
  one retry on a transient `Timeout`/`ConnectionError` **or** a transient HTTP status
  (`USDA_TRANSIENT_STATUS` = 404/5xx — USDA's gateway intermittently serves an HTML error page
  instead of JSON)). Rate limits (429/403) surface as HTTP 429 and fail fast, never silent zeros.
- **`MOCK_GEMINI=1`** short-circuits *both* stages (canned dish list + canned totals, no network).
  The name is historical — it is provider-agnostic, not Gemini-only.
- **Logging** is timestamped, thread-named, and **request-correlated** (`core.logging_config`).
  Every line carries `[req:<id> u:<user_id>]` — a per-request trace id and the calling
  user — so concurrent requests/users are distinguishable. The ids live in
  `contextvars` (`core.request_context`) and are injected onto every record by a
  log-record factory (so startup/uvicorn/library logs render `req:- u:-` rather than
  erroring). An `@app.middleware("http")` in `main.py` binds them per request: the trace id
  comes from an inbound `X-Request-ID` (else generated) and is **echoed back** on the
  response; the user id comes from the `X-User-Id` header the frontend sends on every
  call (`api/client.js`). The middleware also emits the single **access-log line** per
  request (`METHOD /path?query -> status (N ms) from <client-ip>`); uvicorn's own
  `uvicorn.access` logger is disabled in `core.logging_config` because it logs after the
  middleware resets the context (so it couldn't carry `req`/`p`) and would just duplicate
  this line. Because `asyncio.to_thread` copies the context, the
  ids reach the Stage-1/Stage-2 worker threads automatically; the parallel `usda-lookup_*`
  pool workers re-apply them via `usda_service._bind_log_context` (a `ThreadPoolExecutor`
  doesn't inherit contextvars). Set `LOG_LEVEL` (default `INFO`) to change verbosity.

---

## Config & secrets

API keys (`groq_api_key`, `gemini_api_key`, `usda_api_key`) and the vision provider/model live in
the `app_config` table, editable via Settings (`PUT /api/config`, which calls
`usda_service.reload_client` so a key change takes effect immediately; the vision providers all key
per request and read provider/model from config on each `/analyze`, so they need no rebuild) or
seeded from env vars on first launch by `core.config.seed_defaults`.
`GET /api/config` reports only whether each key is set — never the values, and it (with
`PUT /api/config`) is **admin-only**. **Authentication** uses JWT access/refresh tokens signed
with `JWT_SECRET` (HS256); if `JWT_SECRET` is unset a random secret is generated once and
persisted in `app_config` (`jwt_secret`) so sessions survive restarts — **set `JWT_SECRET`
explicitly for a real deployment** so it's rotatable and not DB-bound. CORS is locked down by default (same-origin serving); set `CORS_ORIGINS`
(comma-separated) only if a separate origin must reach the API. `GET /api/health` returns
`{"status":"ok"}` (liveness) and `GET /api/health/ready` runs a `SELECT 1` and returns
`{"status":"ready"}` or 503 (readiness — used by the Docker `HEALTHCHECK`/orchestrator); a global
exception handler logs unhandled errors and returns a clean 500.

**Observability (all opt-in, off by default in local dev):**

- **Prometheus** — `GET /metrics` exposes request metrics in Prometheus text format
  (`prometheus-fastapi-instrumentator`). On by default; disable with `METRICS_ENABLED=0`.
- **Sentry** — error tracking initializes **only when `SENTRY_DSN` is set** (no DSN is ever
  hardcoded, so local runs are unaffected). `SENTRY_TRACES_SAMPLE_RATE` (default `0.0`) controls
  tracing; `environment` is taken from `APP_ENV`. Errors flow to Sentry *in addition to* the
  existing logging + global exception handler.
Interactive docs (`/docs` Swagger UI, `/redoc` ReDoc, `/scalar` Scalar, `/openapi.json` schema)
are on by default; set `APP_ENV=production` to disable them for a shared deployment.

---

## Docker & deployment

A **multi-stage `Dockerfile`** (repo root) builds a single production image: stage 1
(`node:20-alpine`) builds the React app to `frontend/dist`; stage 2
(`ghcr.io/astral-sh/uv:python3.14-bookworm-slim`) installs the locked deps with `uv sync
--frozen --no-dev`, copies the backend + built frontend into the same relative layout the code
serves from (`DIST_DIR = backend/../frontend/dist`), runs as a non-root user, and serves the API
+ frontend on port 8000. Build and run locally:

```bash
docker build -t nutriai .
docker run -p 8000:8000 -e NUTRITION_SOURCE=online -e USDA_API_KEY=<key> nutriai
```

> **Offline USDA index is not in the image.** `usda_local.db` and its source CSVs are gitignored,
> so the container defaults to `APP_ENV=production` + `NUTRITION_SOURCE=online` (set `USDA_API_KEY`).
> To run the image fully offline, mount a prebuilt index at `/app/backend/usda_local.db` and set
> `NUTRITION_SOURCE=offline`.

**Runtime env vars:** `APP_ENV` (`production` disables docs + admin), `JWT_SECRET` (HS256
signing secret — set this in production), `NUTRITION_SOURCE` (`online`|`offline`),
`USDA_API_KEY`, optional `GROQ_API_KEY`/`GEMINI_API_KEY`, `CORS_ORIGINS`, `SENTRY_DSN`
(+ `SENTRY_TRACES_SAMPLE_RATE`), `METRICS_ENABLED`, `LOG_LEVEL`.

### CI/CD (GitHub Actions)

> **Paused pre-launch.** Both workflows currently trigger on `workflow_dispatch` only (manual
> run from the Actions tab); their automatic triggers are kept as comments. To re-enable
> automation, uncomment the `push`/`pull_request`/`tags`/`release` triggers in each file.

- **`.github/workflows/ci.yml`** — `uv sync` then `ruff check`, `ruff format --check`, and
  `pytest` (backend), plus an `npm ci && npm run build` frontend job. (Original trigger: every
  push/PR to `main`/`master`.)
- **`.github/workflows/docker-publish.yml`** — builds the Dockerfile and pushes to **GitHub
  Container Registry** (`ghcr.io/<owner>/ai-nutrition-tracker`) with branch/semver/sha/`latest`
  tags. (Original trigger: push to `main`/`master`, tags `v*`, and releases.)

### Deploying to Koyeb

> **One-click deploy is disabled pre-launch.** Create the Koyeb service manually for now (steps
> below). To restore the one-click button later, add a link to `app.koyeb.com/deploy` with your
> repo and the env defaults (`APP_ENV=production`, `NUTRITION_SOURCE=online`).

Koyeb builds straight from the `Dockerfile` (or pulls the published GHCR image), so no extra
config file is needed. Set the service to **port 8000**, health-check path **`/api/health`**, and
the env vars above (at minimum `USDA_API_KEY` and a vision key, e.g. `GROQ_API_KEY`).

---

## API quick reference

```
# Auth — username + password accounts, JWT access/refresh (Authorization: Bearer <access>)
POST   /api/auth/register         Create account {username, password, name?, avatar_color?} → {user, access_token} + Set-Cookie refresh; 1st user = admin
POST   /api/auth/login            {username, password} → {user, access_token} + Set-Cookie refresh, or 401
POST   /api/auth/refresh          (refresh token from HttpOnly cookie) → {access_token} + rotated Set-Cookie (reuse revokes the chain)
POST   /api/auth/logout           (refresh token from HttpOnly cookie) → revoke it + clear the cookie
GET    /api/auth/me               Current user (from the access token)
POST   /api/auth/change-password  {current_password, new_password} (revokes the caller's refresh tokens)

# Users — own settings + admin-only management
PATCH  /api/users/me              Update own goal {calorie_goal} (500–10000)
GET    /api/users                 (admin) list users
PATCH  /api/users/{id}            (admin) {role?, is_active?} — guards the last admin
POST   /api/users/{id}/reset-password  (admin) {new_password} → must_change_password on next login

GET    /api/health                {status:"ok"} — liveness check
GET    /api/health/ready          {status:"ready"} or 503 — readiness (DB SELECT 1)
GET    /metrics                   Prometheus metrics (text; METRICS_ENABLED=0 to disable)
# Meals/nutrition are scoped to the authenticated user (from the token) — no client-supplied user_id.
POST   /api/meals/analyze         Image → AI analysis (no DB write); returns dishes[] breakdown
POST   /api/meals/log             Save a single analyzed meal (owner = caller)
POST   /api/meals/log-group       Save {group_id, meals:[...]} as a grouped session
GET    /api/meals/timeline        ?page&limit — paginated, grouped by group_id (caller's meals)
GET    /api/meals/group/{id}      Full MealGroupSummary (total_nutrients) — owner-scoped (404 otherwise)
DELETE /api/meals/group/{id}      Delete all meals in a group — owner-scoped
GET    /api/meals/{id}            Full meal detail — owner-scoped (404 otherwise)
PATCH  /api/meals/{id}            Update a meal — owner-scoped
DELETE /api/meals/{id}            Delete a meal — owner-scoped

GET    /api/nutrition/daily       ?date_from&date_to — day totals (caller's meals)
GET    /api/nutrition/monthly     ?year&month — monthly breakdown + averages (caller's meals)

# Config holds the provider API keys — ADMIN ONLY (403 for non-admins).
GET    /api/config                {gemini_api_key_set, groq_api_key_set, usda_api_key_set, nutrition_source, vision_provider, vision_model}
PUT    /api/config                Save any of {gemini_api_key, groq_api_key, usda_api_key, nutrition_source, vision_provider, vision_model}

# Foods — public read-only over the offline USDA index (usda_local.db); 503 until build_usda_db.py is run
GET    /api/foods/search          ?q&data_type&require_all&limit — BM25-ranked FoodSummary[]
GET    /api/foods/{fdc_id}        FoodDetail — description + per-100g macros & micros

# Admin — DEV-ONLY (mounted only when APP_ENV != production) AND admin-only (Bearer admin token); secrets always redacted
GET    /api/admin/tables          ?db=app|local — table + row counts
GET    /api/admin/food-cache      ?query&limit&offset — browse the USDA lookup cache
GET    /api/admin/meals           ?user_id&limit&offset — flat logged-meal view (+ macros/micros)
GET    /api/admin/config          app_config rows; *_api_key values redacted
POST   /api/admin/query/{which}   {sql} — read-only SELECT on app|local DB (mode=ro; SELECT-only; app secrets/password hashes redacted)
```

**Interactive docs (Swagger UI): `http://localhost:8000/docs`** (ReDoc at `/redoc`, Scalar at
`/scalar`, schema at `/openapi.json`). Set `APP_ENV=production` to disable all four **and** the
`/api/admin/*` routes.
The read-only SQL console (`POST /api/admin/query/{which}`) only accepts a single `SELECT`/`WITH`
statement and runs it on a `mode=ro` connection, so writes are impossible; on the app DB, API-key
values, the JWT secret, and the `password_hash` column are redacted from results.
**Group routes are declared before `/{meal_id}`**
to avoid FastAPI routing conflicts.

### Daily reference targets (UI progress bars)

The **calorie goal is per-user and editable** (Settings → *Daily Calorie Goal*, stored on
`users.calorie_goal`, default 2000). The baseline below is a coherent 20% protein / 50% carbs /
30% fat split (sums to exactly 2000 kcal). Energy-linked goals **scale with the calorie goal**
(factor `calorie_goal / 2000`); the sodium limit and the `MicroGrid` vitamin/mineral DVs are
**fixed** (set by body needs, not energy). The single source of truth is `frontend/src/utils/goals.js`.

| Calories | Protein | Carbs | Fat | Fiber | Sugar | Sodium |
|---|---|---|---|---|---|---|
| 2000 kcal (editable) | 100 g | 250 g | 67 g | 28 g | 50 g | 2300 mg (fixed) |
| — | scales | scales | scales | scales | scales | fixed |

Micros are shown as raw values (no goal bars) in a collapsible `MicroGrid`.

---

## Tests

`backend/tests/` — stdlib `unittest` style, **no network** (USDA calls via
`usda_service._client.session.post` are stubbed; the cache points at a temp DB so the real
`nutrition.db` is untouched). Run them with **pytest** (the dev dependency that CI runs) or plain
unittest — both discover the same tests. From `backend/`:

```
uv run pytest                         # what CI runs (pytest config in pyproject.toml)
python -m unittest discover -s tests  # equivalent, no extra deps
```

`test_vision_service.py` covers Stage-1 dish parsing, the build-once pools (`init_clients`), and
per-request client resolution (`_client_for` + the Groq/Gemini/Ollama dispatch); `test_usda_service.py`
covers aliasing, matching, the cache (incl. negative caching), the lookup cap, the curated
dish-lookup gate, transient-timeout retries, and rate-limit propagation. `test_auth.py` covers
the auth flow end-to-end (register/first-user-admin, login, ownership scoping on meals,
admin-only gating, refresh-token rotation + reuse detection, change-password) against a temp DB
with `JWT_SECRET` set.

**Linting:** Ruff is configured in `backend/pyproject.toml` (it now also declares the runtime +
dev deps; see [How to run](#how-to-run)). `ruff` and `pytest` are installed by `uv sync`; from
`backend/` run `uv run ruff check` and `uv run ruff format`. CI enforces `ruff check`,
`ruff format --check`, and `pytest` on every push/PR.

---

## Utility scripts

- `backend/check_alias.py` — validates a **single** food/dish name against the **offline** local
  index (`usda_local.db`) through the same production matching path, printing what the app would
  pick (description + cal/100g) plus the top candidates, for both the dish and ingredient paths.
  Read-only, **no network / key / permission** — the quick "what resolves for this name?" check to
  run **before** adding or changing an alias. From `backend/`: `python check_alias.py "<name>"`
  (`--dish` / `--food` to limit to one path). The `validate-food` skill drives this loop.
- `backend/check_aliases.py` — audits **every** `FOOD_ALIASES`/`DISH_ALIASES` entry against the
  **real USDA API** through the production matching path (read-only, bypasses cache), printing each
  chosen match or `UNMATCHED`. Run from `backend/`: `python check_aliases.py <usda_key>` (or
  `USDA_API_KEY` env / `backend/.env`). Use it **after** editing aliases (makes API calls — ask
  before running per `CLAUDE.md`).
- `backend/list_misses.py` — prints the names USDA matching couldn't resolve (the negative-cached
  misses in `food_cache`, deduped + split offline/online), as the alias-curation worklist. Run
  from `backend/`: `python list_misses.py`. Read-only.
- `check_gemini_limits.py` (project root) — lists available Gemini models with token limits and
  tests an API key. Run: `python check_gemini_limits.py <api_key>`.

---

## What's not built yet

- Swapping the USDA match behind a *matched* whole dish (per-ingredient gram editing + remove and
  custom ingredient search/add are **built** — see the LogMeal review above; only matched dishes
  still scale solely as a whole). Keyboard-nav autocomplete for the add-ingredient search is also
  deferred (today it's a debounced type-to-list).
- **Online (FDC-API) backend for `/api/foods/search`.** The add-ingredient search currently runs
  *only* over the offline index (`usda_local.db`), which is gitignored and **not in the Docker
  image** — so the search box returns 503 in the deployed container (prod defaults to the online
  USDA API) until the index is built/mounted. Wiring `/api/foods/*` to follow the configured
  `nutrition_source` (offline index **or** online FDC API, the same seam Stage 2 already uses via
  `usda_service._search_usda`) would make custom-add work in both local and deployed runs. Deferred:
  the feature is fully usable in local dev today, and the offline/online seam already exists to reuse.
- Single-item LLM nutrient fallback for `unmatched` foods (currently warn-only by design);
  Open Food Facts barcode path; IFCT 2017 for dish-level Indian accuracy.
- Vector-embedding **semantic fallback** for names that still miss after the Stage-1 `usda_name`
  normalization + aliases. Deferred deliberately: prompt-side normalization already captures most
  of the win (the vision LLM *is* a semantic model), and a naive nearest-neighbor fights the
  "rather report unmatched than a confident wrong number" rule (it ranks *sprouted stir-fried*
  ~50 cal and *plain boiled* ~105 cal mung beans as near-identical). If built, it should be a
  **threshold-gated lookup on a miss only** (a local CPU embedding model to stay no-network, USDA
  corpus embedded in `build_usda_db.py`, vectors via `sqlite-vec` or a flat numpy/FAISS file),
  justified by measurement — chiefly the weaker local Ollama 4B, which normalizes regional names
  worse than Groq/Llama-4-Scout.
- **Email-based auth flows** — password reset and email verification are deferred (no SMTP);
  accounts are username + password only, and a forgotten password is reset by an admin
  (`POST /api/users/{id}/reset-password`). The schema leaves room to add email later.
- **Admin user-management UI** — the admin endpoints (`/api/users…`) exist, but there's no
  Settings screen for them yet; use `/docs`.
- **Refresh-token pruning** — `refresh_tokens` rows are revoked/rotated but never deleted, so the
  table grows over time. A lifespan sweep (or periodic job) deleting rows where
  `expires_at < now()` (and old revoked ones) would keep it bounded.
- **Multi-tab refresh grace window** — refresh rotation is strict: if two tabs (sharing the
  `HttpOnly` refresh cookie) refresh concurrently, the second presents an already-rotated
  token and reuse-detection revokes the whole chain, logging both out. A short reuse grace
  window (accept the immediately-previous jti for a few seconds) or a per-tab refresh token
  would smooth this without giving up reuse detection.
- Manual edit of logged nutrition values.
- Keep-image toggle in the LogMeal UI (backend already supports `keep_image: true` on `/meals/log`).
- Data export (CSV / PDF); dark mode; direct camera-open on mobile.
```
