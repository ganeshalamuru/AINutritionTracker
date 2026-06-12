# NutriAI — Session Handoff

## What Was Built

A fully local AI-powered nutrition tracker web app accessible from both desktop and mobile browsers on the same WiFi network. Users photograph meals, get AI-powered macro/micro breakdowns, and track nutrition over time.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14 + FastAPI + SQLAlchemy |
| Database | SQLite (`backend/nutrition.db`) — persists across restarts |
| AI Vision | **Provider-configurable.** Default **Groq · Llama 4 Scout** (`meta-llama/llama-4-scout-17b-16e-instruct`). Gemini/Gemma selectable as fallback. **Only identifies ingredients** (see Two-Stage Nutrition Architecture). |
| Nutrient data | **USDA FoodData Central** API (`usda_api_key`, default `DEMO_KEY`) — supplies real macros/micros; cached in SQLite `food_cache`. |
| Frontend | React 18 + Tailwind CSS (Vite build) |
| Serving | FastAPI serves the React `dist/` as static files on port 8000 |

> **Why Groq?** On this Google free-tier account, every usable Gemini Flash model is capped at
> ~20 requests/day, and `gemma-4-31b-it` has only 383 TPM (can't fit one image request → 504s).
> Groq's free tier gives ~1,000 RPD / 6K TPM / 30 RPM plus the fastest inference. Set the model in
> Settings; each provider uses its own API key (`groq_api_key` / `gemini_api_key`).

---

## How to Run

```powershell
# Dev mode — hot reload (Vite on :8000, FastAPI on :8001):
.\start.ps1 -Dev
$env:MOCK_GEMINI = "1"; .\start.ps1 -Dev

# Production mode — build then serve via FastAPI on :8000:
.\start.ps1
.\start.ps1 -SkipBuild          # skip frontend rebuild (backend-only changes)
$env:MOCK_GEMINI = "1"; .\start.ps1

# Git Bash equivalents:
bash start.sh --dev
bash start.sh
bash start.sh --skip-build
```

- Desktop: `http://localhost:8000` (both dev and production)
- Mobile (same WiFi): run `ipconfig`, find your IPv4 address, open `http://<your-ip>:8000`

> **First-time AI setup:** get a free Groq key at https://console.groq.com/keys (no card) and paste
> it into Settings → "Groq API Key". Optionally seed via `GROQ_API_KEY` env (or `GEMINI_API_KEY`
> for the fallback) before first launch. `MOCK_GEMINI=1` skips all real calls.

> Dev mode: Vite owns :8000 and proxies `/api/*` → FastAPI on :8001. Hot reload works on any `.jsx` / `.css` save. Backend also uses `--reload` so Python changes restart automatically.

> Production mode: `.\start.ps1` (no `-Dev`) builds the React app into `frontend/dist/` and FastAPI serves it as static files on :8000. Use this before sharing with others or testing on mobile with final UI.

> If PowerShell blocks the script: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

> **Important:** Always run `.\start.ps1` (full rebuild) after any frontend code change. `-SkipBuild` will serve stale JS.

---

## Project Structure

```
ai-nutrition-tracker/
├── backend/
│   ├── main.py               # FastAPI app entry, CORS, static serving, lifespan + DB migration + config seeding + logging
│   ├── logging_config.py     # configure_logging(): timestamped formatter on root + uvicorn loggers
│   ├── database.py           # SQLAlchemy engine + get_db dependency
│   ├── models.py             # ORM models: Profile, Meal (with group_id), Macros, Micros, AppConfig
│   ├── schemas.py            # Pydantic models: MealSummary, MealGroupSummary (total_micros), TimelineItem union
│   ├── routers/
│   │   ├── profiles.py       # GET/POST /profiles, POST /profiles/verify (scoped to profile_id), DELETE
│   │   ├── meals.py          # POST /analyze (provider-aware), POST /log, POST /log-group, GET /timeline,
│   │   │                     # GET /group/{group_id}, DELETE /group/{group_id}, DELETE /{id}
│   │   └── nutrition.py      # GET /daily, GET /monthly summaries
│   ├── services/
│   │   ├── gemini_service.py # Vision dispatch (Groq/Gemini/Ollama) → compact JSON; timeout+retry; timestamped logging; MOCK_GEMINI=1
│   │   ├── nutrition_db.py    # Stage-2 USDA lookup: aliasing, matching, cache, per-meal lookup cap
│   │   └── nutrition_data/    # Pure reference data (no logic), re-imported by nutrition_db:
│   │       ├── config.py      #   USDA endpoint + tuning + USDA_MAX_LOOKUPS + CACHE_VERSION
│   │       ├── aliases.py     #   FOOD_ALIASES, COOKING_ADJECTIVES, SIMPLIFY_STRIP_WORDS, GENERIC_WORDS
│   │       ├── nutrient_map.py#   FDC_NUTRIENT_MAP, ENERGY_FALLBACK_IDS
│   │       └── mock.py        #   MOCK_MACROS, MOCK_MICROS
│   ├── uploads/              # Temp image staging (auto-purged after 1 hour)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx
│   │   ├── context/ProfileContext.jsx
│   │   ├── api/client.js
│   │   ├── pages/
│   │   │   ├── ProfileSelect.jsx   # PIN login, guest mode, create profile
│   │   │   ├── Home.jsx            # Today's summary + grouped meal cards + modal
│   │   │   ├── LogMeal.jsx         # Multi-photo upload → sequential AI analysis → confirm log
│   │   │   ├── Timeline.jsx        # Paginated meal history + grouped meal cards + modal
│   │   │   ├── Monthly.jsx         # Bar chart + monthly averages
│   │   │   └── Settings.jsx        # API key, profile management, WiFi help
│   │   └── components/
│   │       ├── layout/  (Layout, TopBar, BottomNav)
│   │       ├── meal/    (MealCard, GroupedMealCard, MealDetailModal, MacroRing, MicroGrid)
│   │       ├── summary/ (MacroProgressBar)
│   │       └── shared/  (Spinner, Toast, EmptyState, ConfirmModal)
├── start.ps1        # One-command startup (PowerShell)
├── start.sh         # One-command startup (Git Bash)
└── .gitignore       # Excludes: node_modules, dist, nutrition.db, uploads/, .env
```

---

## Key Design Decisions

### Vision Provider Architecture
Provider + model are configurable via `AppConfig` keys `vision_provider` + `vision_model` (defaults `groq` / `meta-llama/llama-4-scout-17b-16e-instruct`, seeded in `main.py` lifespan). `gemini_service.py` dispatches through a `PROVIDERS` map: `_groq_analyze` (groq SDK, base64 image, JSON mode), `_gemini_analyze` (covers `gemini-*` + `gemma-*`), `_ollama_analyze` (stub for a future fully-local option). `get_api_key(db, provider)` in `meals.py` returns the matching key (`groq_api_key` / `gemini_api_key`). Settings has a provider/model dropdown plus a key field per provider.

**Latency/throughput levers:** each call has a **15s timeout + one retry** (non-quota errors only) so it never hangs; images are **downscaled client-side to 384px** in `LogMeal.jsx` (flat ~258 image tokens, no tiling); output is a compact JSON (see Vision Prompt below).

### API Key Storage
API keys stored in `app_config` SQLite table (`groq_api_key`, `gemini_api_key`), set via Settings UI OR seeded from `GROQ_API_KEY` / `GEMINI_API_KEY` env on first startup (`main.py` lifespan).

### Mock Mode
Set `MOCK_GEMINI=1` env var before starting to skip all real model calls and return canned nutrition data (`gemini_service.py:MOCK_RESPONSE`). Name is historical — it applies to every provider, not just Gemini.

### Multi-Photo Grouped Meals
Multiple photos from LogMeal are analyzed independently (one vision call each) and grouped under a shared `group_id` UUID. Groups are stored as individual `Meal` rows with the same `group_id`. The timeline backend collapses them into a `MealGroupSummary` with summed macros AND summed micros. Home.jsx does the same grouping client-side from the flat daily summary (macros only), but fetches full group data (with micros) from `GET /meals/group/{group_id}` when the modal is opened.

### Meal Detail Modal
Clicking any MealCard or GroupedMealCard opens a bottom-sheet modal (`MealDetailModal`). Shows all 7 macros (calories, protein, carbs, fat, fiber, sugar, sodium) + 17 micros (collapsible). Groups have Totals / Breakdown tabs. Totals tab shows summed macros + summed micros.

### Group Deletion
- On the card: "Remove" button calls `DELETE /meals/group/{group_id}` directly.
- In the modal header: "Remove session" button does the same.
- Individual sub-meal removal still available in the Breakdown tab.

### Confirm Modal
All destructive actions use a custom `ConfirmModal` component (`components/shared/ConfirmModal.jsx`). No browser `confirm()` popups anywhere. Backdrop tap dismisses.

### Timeline Item Type Discriminator
`GET /meals/timeline` returns `List[Union[MealGroupSummary, MealSummary]]` using Pydantic discriminated union on `item_type: Literal["meal"|"group"]`. Frontend checks `item.item_type` to decide which card to render.

### Group Micros Endpoints
- `GET /meals/group/{group_id}` — returns full `MealGroupSummary` with `total_micros` summed from DB. Used by Home.jsx when opening group modal.
- `DELETE /meals/group/{group_id}` — deletes all meals with that group_id.
- Both routes are declared BEFORE `/{meal_id}` to avoid FastAPI routing conflicts.

### DB Migration (group_id)
`group_id TEXT` column added to `meals` table on server startup via idempotent `ALTER TABLE` wrapped in try/except in `main.py` lifespan. Safe for existing databases.

### Datetime Display & Timezone-Correct Day Filtering
Backend stores UTC datetimes without timezone suffix (naive UTC strings). Frontend appends `"Z"` before parsing: `new Date(x.logged_at + "Z")` — tells the browser it's UTC so `toLocaleTimeString` converts to device local time correctly.

For the daily summary, `Home.jsx` computes the user's local midnight using `new Date(year, month, day)` (JS Date constructor uses local timezone), then calls `.toISOString()` to get the UTC equivalent. It sends `date_from` and `date_to` as UTC ISO strings via axios `params` (auto URL-encoded). The backend filters with a range comparison (`logged_at >= date_from AND logged_at < date_to`) rather than `func.date()`, which ensures meals near midnight are always included regardless of the user's timezone offset.

### PIN Auth (scoped)
`POST /profiles/verify` requires `{ profile_id, pin }`. Backend fetches profile by ID first, then checks PIN — prevents entering Profile B's PIN on Profile A's screen to log in as B.

### Guest Mode
Frontend-only sentinel `{ id: 0, isGuest: true }` — never written to DB. Analysis works, Log button replaced with "Create a profile" CTA.

### Browser Compatibility
`crypto.randomUUID()` is not available in all browser contexts. A `uid()` fallback using `Math.random().toString(36)` is used instead in `LogMeal.jsx` for photo IDs and group IDs.

---

## Two-Stage Nutrition Architecture (replaced single-shot estimation, 2026-06-12)
**Problem:** asking one vision-LLM call to both perceive the meal AND recall exact nutrient facts produced fabricated numbers (micros especially) — provider swaps couldn't fix it (structural). **Fix:** split perception from nutrient lookup.

- **Stage 1 — perception** (`gemini_service.py`): the vision model returns ONLY a compact ingredient list, no nutrients:
  `{"n":meal_name,"t":meal_type,"c":confidence,"i":[{"f":"ingredient","g":grams},...]}`. The prompt has a hard "NEVER output a dish/recipe/beverage name" rule + few-shot decomposition examples (dosa→rice+urad dal+oil, sambar→toor dal+veg+tamarind, coconut chutney→coconut+chana dal, filter coffee→coffee+milk+sugar, palak paneer→spinach+paneer+cream+onion+oil) — early tests showed it left South-Indian dishes undecomposed, which left them `unmatched`. `_parse_compact()` → `{meal_name, meal_type, confidence, items}`; `_parse_items()` drops junk/blank entries (bad grams → 0). Single-provider call, 15s timeout + retry once, MOCK_GEMINI returns a mock item list.
- **Stage 2 — nutrient lookup** (`backend/services/nutrition_db.py`): `nutrients_for_items(items, usda_api_key)` searches **USDA FoodData Central** per ingredient (`/foods/search`, dataTypes Foundation/SR Legacy/Survey FNDDS, pageSize=5), scales per-100g nutrients by `grams/100`, sums into the full 7-macro + 17-micro schema, and returns a **4-tuple `(macros, micros, unmatched, skipped)`**: `unmatched[]` = foods USDA can't resolve, `skipped[]` = foods not looked up because of the per-meal lookup cap (both contribute 0). `FDC_NUTRIENT_MAP` maps USDA nutrientIds → schema keys; energy falls back to Atwater ids if 1008 absent. Lookups cached in SQLite `food_cache` (created in `main.py` lifespan + lazily in the service) so repeats cost no API calls. MOCK_GEMINI returns canned totals (no network).
  - **Per-meal lookup cap (`USDA_MAX_LOOKUPS = 8`):** caps distinct *uncached* ingredient lookups per meal, prioritizing the largest portions (they dominate the macros). **Cached ingredients are always resolved and never count against the cap.** Ingredients beyond the cap go to `skipped[]`. Keeps per-meal USDA usage bounded; a typical 8-item meal still fully resolves, and dropped tiny items get cached on a later encounter. *(There is no USDA bulk/batch name-search endpoint — `/foods/search` is one query per call — so we cap rather than batch.)*
- **Wiring:** `/analyze` runs Stage 1 (`asyncio.to_thread`) then Stage 2 (`asyncio.to_thread`), reads `usda_api_key` from config. `AnalyzeResponse` gained `items[]` + `unmatched[]` + `skipped[]`. `LogMeal.jsx` shows an "Identified ingredients" panel; unmatched foods are highlighted with an undercount warning, skipped foods are greyed/struck-through with a "not counted" note. `MicroGrid.jsx` still renders only non-zero micros.

**Stage-2 reliability + matching (2026-06-12):** uses **POST** `/foods/search` (dataType as a JSON array, `pageSize=5`). `_pick_best()` prefers generic data types (Foundation > SR Legacy > FNDDS), then query-token coverage, shortest description, highest score — so "chicken breast, cooked" resolves to a generic breast, not breaded tenders. `_simplify()` retries a miss once with a simpler query ("onion, fried"→"onion", strips text after the comma + cooking adjectives). Lookups are **deduped + parallelized** (`ThreadPoolExecutor`). **Rate limits fail loudly:** `UsdaRateLimitError` (HTTP 429/403 or body `error.code == OVER_RATE_LIMIT`) propagates → `/analyze` returns a **429** "add your USDA key" message instead of silently zeroing the meal. **Every external USDA call logs its request and response** via the `nutriai.nutrition_db` logger. **Key limits:** DEMO_KEY = 30/hr **+ 50/day** (a couple of meals exhaust it); a free signed key = 1,000/hr — paste it in Settings.

**Match quality (alias map + head-noun gate):** the model's ingredient names are normalized through `FOOD_ALIASES` (~34 common/Indian staples → generic cooked USDA queries, e.g. `basmati rice`→`rice white cooked`, `yogurt`→`yogurt plain whole`, `paneer`→`cheese paneer`) before searching. The primary search uses `requireAllWords=True`; a simplified fallback uses `False`. `_pick_best` applies a **head-noun gate** (`_food_noun` = last non-generic token, matched stem-insensitively via `_stem`): a result whose description lacks the food word is rejected → the ingredient is reported `unmatched` (UI warns, contributes 0) rather than guessed (so `mint leaves` no longer becomes "Amaranth leaves"). Survivors rank food-noun-as-first-word > token coverage > data type > shorter desc > score. Cache invalidation: `CACHE_VERSION` (currently `"5"`); the `main.py` lifespan purges `food_cache` when `app_config.food_cache_version` differs, so improved matching isn't masked by stale rows.

**Spices + general miss-recovery (latest):** the model emits "turmeric powder / red chili powder / cumin powder / cinnamon stick", but USDA files these as "Spices, turmeric, ground / chili powder / cumin seed / cinnamon, ground" — strict `requireAllWords=True` couldn't match (descriptor word "powder"/"stick" absent from USDA) and `_simplify()` (cooking-adjectives only) never stripped it, so no loose retry fired → all four `unmatched`. Fixed two ways: (1) spice entries added to `FOOD_ALIASES` (turmeric/chili/cumin/cinnamon/coriander/pepper + `haldi`/`jeera`/`chilli` variants); (2) `_simplify()` now strips a broader `SIMPLIFY_STRIP_WORDS = COOKING_ADJECTIVES | {powder, stick, ground, seed, whole, sliced, chopped, dried}`, so any un-aliased "X powder" self-heals via a loose retry on "X". Verify real matches with `python check_aliases.py <usda_key>`.

**Tests:** `backend/tests/` (stdlib `unittest`, no network — stubs `requests.post`, points the cache at a temp DB so the real `nutrition.db` is never touched). Run from `backend/`: `python -m unittest discover -s tests`.

**Why USDA + decomposition for Indian food:** USDA is weak on composite Indian *dishes* but strong on their *ingredients*; decomposing in Stage 1 sidesteps the dish-coverage gap and works for any cuisine. **Known limitations:** portion grams are LLM-estimated; some specific phrasings may still miss. Future: editable ingredients/grams before logging (re-run Stage 2), single-item LLM fallback for USDA misses, Open Food Facts barcode path, IFCT 2017 for dish-level Indian accuracy.

> Get a free USDA key at https://fdc.nal.usda.gov/api-key-signup (Settings → "USDA Food Database Key"); `DEMO_KEY` works at a low limit out-of-box. Seed via `USDA_API_KEY` env on first launch.

---

## Error Handling & Logging
`meals.py` maps provider errors to HTTP (messages are provider-neutral, include the raw error):
- **Per-minute rate limit** (`429`/`rate`/`per_minute`) → 429 "wait 60 seconds"
- **Daily quota exhausted** (`quota`/`daily`/`resource_exhausted`/`per_day`) → 429
- **Timeout / no response** (`timeout`/`timed out`/`deadline`/`504`) → 504 (never hangs)

The service retries once on any non-quota error (15s timeout each). **Logging:** `backend/logging_config.py` `configure_logging()` applies a timestamped formatter to the root + uvicorn loggers (called from `main.py` and `gemini_service.py`), so **every** log line is timestamped. The `nutriai.vision` logger emits one line per request and per response with provider, model, latency, and the model's raw output (plus retries/errors). Frontend `client.js` has a 25s axios timeout as a UI safety net.

---

## Issues Fixed Across Sessions

| Issue | Fix |
|---|---|
| Pillow failed to build on Windows | Removed from requirements — not needed |
| `gemini-1.5-flash` model not found | Updated to `gemini-3.5-flash` |
| Quota exhausted error was cryptic | Added friendly messages + raw error; distinguish rate vs daily quota |
| Profile switch reloaded same page | `logout()` called before `navigate("/")` in TopBar |
| `uvicorn` not in PATH on Windows | All scripts use `python -m uvicorn` |
| Entering another profile's PIN logged in as that profile | `/profiles/verify` now requires `profile_id` |
| Times shown in UTC instead of local | Append `"Z"` to datetime strings before `new Date()` parsing |
| `crypto.randomUUID` not a function (browser compat) | Replaced with `uid()` using `Math.random().toString(36)` |
| MealCard showed no fiber/sugar/sodium | Added to MealCard row + full detail in MealDetailModal |
| Single photo flow broke when multi-photo added | Photo IDs generated before any `await` |
| Grouped meals showed no micronutrients | Added `total_micros` to `MealGroupSummary`; new `GET /meals/group/{id}` endpoint |
| No way to remove a grouped meal session | "Remove" button on GroupedMealCard + "Remove session" in modal header |
| Browser `confirm()` popups everywhere | Replaced with `ConfirmModal` component across all 4 files |
| Two clicks needed to see micros in LogMeal | Removed outer toggle; MicroGrid's own toggle is now the single click |
| Gemini call blocking FastAPI event loop | Wrapped `analyze_meal_image` in `asyncio.to_thread()` in `/analyze` endpoint |
| No way to give AI context about a meal | Added `user_note` optional field to `/analyze`; LogMeal shows hint input before analyze |
| LogMeal auto-analyzed on file pick (wasted quota) | Removed auto-analyze; flow is now: upload → type hint → click Analyze button |
| Home page meals showed oldest first | Changed `nutrition.py` daily query to `.order_by(Meal.logged_at.desc())` |
| No micros for individual meals in group breakdown | `SubMealCard` lazy-fetches `GET /meals/{id}` on "Show micros" toggle; cached per session |
| Two clicks to see sub-meal micros (Show micros + MicroGrid toggle) | Added `alwaysOpen` prop to `MicroGrid`; `SubMealCard` passes it so grid opens immediately |
| No hot reload during frontend development | Added `-Dev` / `--dev` mode to start scripts: Vite on :8000, FastAPI on :8001 |
| Stored dates had `+00:00` suffix (broke frontend `+ "Z"` parsing) | Stripped timezone suffix from all existing DB rows via SQL UPDATE |
| Daily summary fetched wrong day for non-UTC timezones | `Home.jsx` sends local midnight as UTC ISO range (`date_from`/`date_to`) via axios `params`; backend filters `logged_at >= date_from AND logged_at < date_to` instead of `func.date()` |
| Deprecated `datetime.utcnow()` / `datetime.utcfromtimestamp()` calls | Replaced with `datetime.now(timezone.utc)` / `datetime.fromtimestamp(..., tz=timezone.utc)` across `main.py`, `models.py`, `nutrition.py` |
| Gemini free tier unusable (~20 RPD on Flash; Gemma 383 TPM can't fit an image → 504s) | Switched default to **Groq · Llama 4 Scout** (~1k RPD / 6K TPM); made provider/model configurable with Gemini fallback |
| Slow / token-heavy analysis | Compact JSON output, **384px** client-side image downscale, `max_tokens` cap, `temperature=0` |
| App hung forever when the model didn't respond | **15s timeout + retry once** per call; 504 mapped to a clear error; 25s axios safety-net |
| Same fixed 8 micros reported for every meal | Model now returns a **variable object** of the major micros for that specific meal (from the full 17); `MicroGrid` shows only the reported ones |
| LLM-estimated macros/micros were inaccurate (esp. fabricated micros) | **Two-stage architecture**: vision model identifies ingredients + grams; **USDA FoodData Central** supplies real nutrient numbers (cached in `food_cache`). See Two-Stage Nutrition Architecture section. |
| Logs had no timestamps | `logging_config.py` `configure_logging()` timestamps root + uvicorn loggers; `nutriai.vision` logs every request/response with provider, model, latency, raw output |
| Common spices (turmeric/chili/cumin/cinnamon powder) always `unmatched` | Added spice `FOOD_ALIASES` mapping to USDA "Spices, …" wording + broadened `_simplify()` strip set (`SIMPLIFY_STRIP_WORDS`) so "X powder/stick" retries loosely as "X" |
| Too many USDA calls per meal (~1 per distinct uncached ingredient) | Per-meal lookup cap `USDA_MAX_LOOKUPS = 8` — largest portions first, cached lookups free; overflow → `skipped[]` shown "not counted" in LogMeal. (No USDA bulk name-search endpoint exists.) |
| Large `nutrition_db.py` mixed data + logic | Extracted all reference tables/constants into a `services/nutrition_data/` package (re-imported, public surface unchanged) |

---

## API Quick Reference

```
GET    /api/profiles              List all profiles
POST   /api/profiles              Create profile {name, pin, avatar_color}
POST   /api/profiles/verify       Verify {profile_id, pin} → returns profile or 401
DELETE /api/profiles/{id}         Soft-delete profile

POST   /api/meals/analyze         Upload image → AI nutrition analysis (no DB write)
POST   /api/meals/log             Save single analyzed meal to DB
POST   /api/meals/log-group       Save {group_id, meals:[...]} as grouped meal session
GET    /api/meals/timeline        ?profile_id&page&limit — paginated, grouped by group_id
GET    /api/meals/group/{id}      Full MealGroupSummary with total_macros + total_micros
DELETE /api/meals/group/{id}      Delete all meals in a group
GET    /api/meals/{id}            Full meal detail with macros + micros
DELETE /api/meals/{id}            Delete meal

GET    /api/nutrition/daily       ?profile_id&date        — today's totals
GET    /api/nutrition/monthly     ?profile_id&year&month  — monthly breakdown + averages

GET    /api/config                {gemini_api_key_set, groq_api_key_set, usda_api_key_set, vision_provider, vision_model}
PUT    /api/config                Save any of {gemini_api_key, groq_api_key, usda_api_key, vision_provider, vision_model}
```

Interactive API docs: `http://localhost:8000/docs`

---

## Daily Reference Targets (UI progress bars)

| Nutrient | Goal |
|---|---|
| Calories | 2000 kcal |
| Protein | 150 g |
| Carbs | 250 g |
| Fat | 65 g |

Micros displayed as raw values (no goal bars) in collapsible MicroGrid.

---

## Utility Scripts

- `check_gemini_limits.py` — lists available Gemini models with token limits, tests API key connectivity, shows free-tier RPM/RPD for known models. Run: `python check_gemini_limits.py <api_key>` or no args if `backend/.env` has the key.
- `backend/check_aliases.py` — audits every `FOOD_ALIASES` entry (+ a few common foods) against the **real** USDA API through the production matching path, printing each food's chosen match (description, dataType, cal/100g) or UNMATCHED with the raw candidates. Read-only, bypasses cache. Run from `backend/`: `python check_aliases.py <usda_key>` (or `USDA_API_KEY` env / `backend/.env`). Use it after editing aliases to confirm matches; last audit: **77/79 matched** (misses: `curd rice`, `poha`).

## Tests
`backend/tests/` — stdlib `unittest`, no network (stubs `requests.post`, temp-DB cache so the real `nutrition.db` is untouched). Run from `backend/`: `python -m unittest discover -s tests` (25 tests).

---

## What's Not Built Yet (potential next steps)

- **Editable ingredients/grams before logging (highest-leverage next step).** The data layer (USDA matching) is accurate now; the biggest remaining error source is the LLM's per-ingredient **gram estimates**. A review step in `LogMeal` to adjust each ingredient's grams (and optionally swap the matched food), then re-run Stage 2 via a `POST /meals/recompute` endpoint, would let the user correct portions directly. `AnalyzeResponse` already returns `items[]` + `unmatched[]` to build this on.
- Single-item LLM nutrient fallback for `unmatched` foods (currently warn-only by design); Open Food Facts barcode path; IFCT 2017 for dish-level Indian accuracy.
- Custom daily calorie/macro goals per profile
- Edit meal nutrition values manually after logging
- Keep-image toggle in the Log Meal UI (backend supports it via `keep_image: true` in `/meals/log`)
- Push/export data (CSV, PDF report)
- Dark mode
- Camera direct-open on mobile (currently uses gallery picker; `capture="environment"` conflicts with `multiple`)
