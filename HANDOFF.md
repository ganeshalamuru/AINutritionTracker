# NutriAI — Session Handoff

## What Was Built

A fully local AI-powered nutrition tracker web app accessible from both desktop and mobile browsers on the same WiFi network. Users photograph meals, get AI-powered macro/micro breakdowns, and track nutrition over time.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14 + FastAPI + SQLAlchemy |
| Database | SQLite (`backend/nutrition.db`) — persists across restarts |
| AI Vision | Google Gemini (`gemini-3.5-flash` default — valid model, confirmed in API) |
| Frontend | React 18 + Tailwind CSS (Vite build) |
| Serving | FastAPI serves the React `dist/` as static files on port 8000 |

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

> Dev mode: Vite owns :8000 and proxies `/api/*` → FastAPI on :8001. Hot reload works on any `.jsx` / `.css` save. Backend also uses `--reload` so Python changes restart automatically.

> Production mode: `.\start.ps1` (no `-Dev`) builds the React app into `frontend/dist/` and FastAPI serves it as static files on :8000. Use this before sharing with others or testing on mobile with final UI.

> If PowerShell blocks the script: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

> **Important:** Always run `.\start.ps1` (full rebuild) after any frontend code change. `-SkipBuild` will serve stale JS.

---

## Project Structure

```
ai-nutrition-tracker/
├── backend/
│   ├── main.py               # FastAPI app entry, CORS, static file serving, lifespan + DB migration
│   ├── database.py           # SQLAlchemy engine + get_db dependency
│   ├── models.py             # ORM models: Profile, Meal (with group_id), Macros, Micros, AppConfig
│   ├── schemas.py            # Pydantic models: MealSummary, MealGroupSummary (total_micros), TimelineItem union
│   ├── routers/
│   │   ├── profiles.py       # GET/POST /profiles, POST /profiles/verify (scoped to profile_id), DELETE
│   │   ├── meals.py          # POST /analyze, POST /log, POST /log-group, GET /timeline,
│   │   │                     # GET /group/{group_id}, DELETE /group/{group_id}, DELETE /{id}
│   │   └── nutrition.py      # GET /daily, GET /monthly summaries
│   ├── services/
│   │   └── gemini_service.py # Gemini Flash image → structured JSON nutrition data; MOCK_GEMINI=1 support
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

### API Key Storage
Gemini API key stored in `app_config` SQLite table (set via Settings UI) OR loaded from `backend/.env` on first startup.

### Mock Gemini Mode
Set `MOCK_GEMINI=1` env var before starting to skip all Gemini API calls and return canned nutrition data. Useful for UI testing without burning free quota. Mock response defined in `gemini_service.py:MOCK_RESPONSE`.

### Multi-Photo Grouped Meals
Multiple photos from LogMeal are analyzed independently (one Gemini call each) and grouped under a shared `group_id` UUID. Groups are stored as individual `Meal` rows with the same `group_id`. The timeline backend collapses them into a `MealGroupSummary` with summed macros AND summed micros. Home.jsx does the same grouping client-side from the flat daily summary (macros only), but fetches full group data (with micros) from `GET /meals/group/{group_id}` when the modal is opened.

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

## Gemini Prompt
Returns **pure JSON** with:
- `meal_name`, `meal_type`, `confidence` (high/medium/low), `estimated_serving`
- `macros`: calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg
- `micros`: 11 vitamins (A/D/E/K/C/B1/B2/B3/B6/B12/folate) + 6 minerals (calcium/iron/magnesium/potassium/zinc/phosphorus)

All unknown values default to `0`. Code strips markdown fences as fallback.

---

## Gemini Error Handling
`meals.py` distinguishes two quota error types:
- **Per-minute rate limit** (`429`/`rate`/`per_minute` in error): "wait 60 seconds"
- **Daily quota exhausted** (`quota`/`daily`/`resource_exhausted`/`per_day`): "resets at UTC midnight"
Raw Gemini error is appended to the message so the user can diagnose. All errors also `print()` to terminal with `[Gemini error]` prefix.

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

GET    /api/config                Check if API key is set
PUT    /api/config                Save {gemini_api_key}
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

---

## What's Not Built Yet (potential next steps)

- Custom daily calorie/macro goals per profile
- Edit meal nutrition values manually after logging
- Keep-image toggle in the Log Meal UI (backend supports it via `keep_image: true` in `/meals/log`)
- Push/export data (CSV, PDF report)
- Dark mode
- Camera direct-open on mobile (currently uses gallery picker; `capture="environment"` conflicts with `multiple`)
