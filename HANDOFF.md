# NutriAI — Session Handoff

## What Was Built

A fully local AI-powered nutrition tracker web app accessible from both desktop and mobile browsers on the same WiFi network. Users photograph meals, get AI-powered macro/micro breakdowns, and track nutrition over time.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.14 + FastAPI + SQLAlchemy |
| Database | SQLite (`backend/nutrition.db`) — persists across restarts |
| AI Vision | Google Gemini 2.5 Flash (`gemini-2.5-flash`) |
| Frontend | React 18 + Tailwind CSS (Vite build) |
| Serving | FastAPI serves the React `dist/` as static files on port 8000 |

---

## How to Run

```powershell
# First run or after frontend changes (installs deps + builds frontend):
.\start.ps1

# Subsequent runs (skip rebuild, faster):
.\start.ps1 -SkipBuild

# Git Bash equivalent:
bash start.sh
bash start.sh --skip-build
```

- Desktop: `http://localhost:8000`
- Mobile (same WiFi): run `ipconfig`, find your IPv4 address, open `http://<your-ip>:8000`

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
│   ├── schemas.py            # Pydantic models: MealSummary, MealGroupSummary, TimelineItem union, etc.
│   ├── routers/
│   │   ├── profiles.py       # GET/POST /profiles, POST /profiles/verify (scoped to profile_id), DELETE
│   │   ├── meals.py          # POST /analyze, POST /log, POST /log-group, GET /timeline, DELETE
│   │   └── nutrition.py      # GET /daily, GET /monthly summaries
│   ├── services/
│   │   └── gemini_service.py # Gemini Flash image → structured JSON nutrition data
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
│   │       └── shared/  (Spinner, Toast, EmptyState)
├── start.ps1        # One-command startup (PowerShell)
├── start.sh         # One-command startup (Git Bash)
└── .gitignore       # Excludes: node_modules, dist, nutrition.db, uploads/, .env
```

---

## Key Design Decisions

### API Key Storage
Gemini API key stored in `app_config` SQLite table (set via Settings UI) OR loaded from `backend/.env` on first startup.

### Multi-Photo Grouped Meals
Multiple photos from LogMeal are analyzed independently (one Gemini call each) and grouped under a shared `group_id` UUID. Groups are stored as individual `Meal` rows with the same `group_id`. The timeline backend collapses them into a `MealGroupSummary` with summed macros. Home.jsx does the same grouping client-side from the flat daily summary.

### Meal Detail Modal
Clicking any MealCard or GroupedMealCard opens a bottom-sheet modal (`MealDetailModal`). Shows all 7 macros (calories, protein, carbs, fat, **fiber, sugar, sodium**) + 17 micros. Groups have Totals / Breakdown tabs. The old expand-dropdown in MealCard is removed.

### Timeline Item Type Discriminator
`GET /meals/timeline` returns `List[Union[MealGroupSummary, MealSummary]]` using Pydantic discriminated union on `item_type: Literal["meal"|"group"]`. Frontend checks `item.item_type` to decide which card to render.

### DB Migration (group_id)
`group_id TEXT` column added to `meals` table on server startup via idempotent `ALTER TABLE` wrapped in try/except in `main.py` lifespan. Safe for existing databases.

### Datetime Display
Backend stores UTC datetimes without timezone suffix. Frontend appends `"Z"` before parsing: `new Date(x.logged_at + "Z")` — tells the browser it's UTC so `toLocaleTimeString` converts to device local time correctly.

### PIN Auth (scoped)
`POST /profiles/verify` now requires `{ profile_id, pin }`. Backend fetches profile by ID first, then checks PIN — prevents entering Profile B's PIN on Profile A's screen to log in as B.

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

## Issues Fixed This Session

| Issue | Fix |
|---|---|
| Pillow failed to build on Windows | Removed from requirements — not needed |
| `gemini-1.5-flash` model not found | Updated to `gemini-2.5-flash` |
| Quota exhausted error was cryptic | Added friendly "wait 60 seconds" message for HTTP 429 |
| Profile switch reloaded same page | `logout()` called before `navigate("/")` in TopBar |
| `uvicorn` not in PATH on Windows | All scripts use `python -m uvicorn` |
| Entering another profile's PIN logged in as that profile | `/profiles/verify` now requires `profile_id` and checks PIN against that specific profile |
| Times shown in UTC instead of local | Append `"Z"` to datetime strings before `new Date()` parsing |
| `crypto.randomUUID` not a function (browser compat) | Replaced with `uid()` using `Math.random().toString(36)` |
| MealCard showed no fiber/sugar/sodium | Added to MealCard row + full detail in MealDetailModal |
| Single photo flow broke when multi-photo added | Photo IDs generated before any `await`; file input cleared synchronously before async work |

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

## What's Not Built Yet (potential next steps)

- Custom daily calorie/macro goals per profile
- Edit meal nutrition values manually after logging
- Keep-image toggle in the Log Meal UI (backend supports it via `keep_image: true` in `/meals/log`)
- Push/export data (CSV, PDF report)
- Dark mode
- Per-sub-meal micronutrient display in grouped meal modal (currently shows totals only)
- Camera direct-open on mobile (currently uses gallery picker; `capture="environment"` conflicts with `multiple`)
