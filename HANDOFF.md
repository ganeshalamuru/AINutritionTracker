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
# First run (installs deps + builds frontend):
.\start.ps1

# Subsequent runs (skip rebuild, faster):
.\start.ps1 -SkipBuild

# Or double-click:
start.bat
```

- Desktop: `http://localhost:8000`
- Mobile (same WiFi): run `ipconfig`, find your IPv4 address, open `http://<your-ip>:8000`

> If PowerShell blocks the script: `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`

---

## Project Structure

```
ai-nutrition-tracker/
├── backend/
│   ├── main.py               # FastAPI app entry, CORS, static file serving, lifespan
│   ├── database.py           # SQLAlchemy engine + get_db dependency
│   ├── models.py             # ORM models: Profile, Meal, Macros, Micros, AppConfig
│   ├── schemas.py            # Pydantic request/response models
│   ├── routers/
│   │   ├── profiles.py       # GET/POST /profiles, POST /profiles/verify, DELETE
│   │   ├── meals.py          # POST /analyze, POST /log, GET /timeline, DELETE
│   │   └── nutrition.py      # GET /daily, GET /monthly summaries
│   ├── services/
│   │   └── gemini_service.py # Gemini Flash image → structured JSON nutrition data
│   ├── uploads/              # Temp image staging (auto-purged after 1 hour)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── App.jsx                        # React Router + protected routes
│   │   ├── context/ProfileContext.jsx     # Global active profile state (localStorage)
│   │   ├── api/client.js                  # Axios instance (baseURL: /api)
│   │   ├── pages/
│   │   │   ├── ProfileSelect.jsx          # PIN login, guest mode, create profile
│   │   │   ├── Home.jsx                   # Today's calorie ring + macro bars + meal list
│   │   │   ├── LogMeal.jsx                # Photo upload → AI analysis → confirm log
│   │   │   ├── Timeline.jsx               # Paginated meal history grouped by date
│   │   │   ├── Monthly.jsx                # Bar chart + monthly averages
│   │   │   └── Settings.jsx               # API key, profile management, WiFi help
│   │   └── components/
│   │       ├── layout/  (Layout, TopBar, BottomNav)
│   │       ├── meal/    (MealCard, MacroRing, MicroGrid)
│   │       ├── summary/ (MacroProgressBar)
│   │       └── shared/  (Spinner, Toast, EmptyState)
├── start.ps1        # One-command startup (PowerShell)
├── start.bat        # Double-click fallback
└── .env.example     # Contains GEMINI_API_KEY (copied to backend/.env on first run)
```

---

## Key Design Decisions

### API Key Storage
The Gemini API key is stored in the `app_config` SQLite table (set via Settings UI) OR loaded from `backend/.env` on first startup. The `.env` value seeds the DB on first run only — subsequent updates go through the Settings page.

### Image Flow
1. Photo uploaded to `/api/meals/analyze` → saved as `uploads/<uuid>.jpg`
2. Gemini analyzes the bytes → returns macros + 17 micronutrients as JSON
3. User reviews and confirms → `/api/meals/log` writes to DB
4. Temp image deleted after logging (default). User can toggle `keep_image: true` per meal.
5. On server start/stop, orphaned uploads older than 1 hour are purged automatically.

### Guest Mode
Guest is a frontend-only sentinel `{ id: 0, isGuest: true }` — never written to DB. Analysis works normally; the Log button is replaced with a "Create a profile" CTA.

### PIN Auth
4-digit PIN stored as plain text in SQLite. No hashing — this is a local personal app with no network security model.

### Profile Switching
Clicking the avatar in TopBar calls `logout()` (clears localStorage) then navigates to `/`. The route guard then shows ProfileSelect instead of bouncing back to `/home`.

---

## Gemini Prompt
The AI is prompted to return **pure JSON only** (no markdown) with this structure:
- `meal_name`, `meal_type`, `confidence` (high/medium/low), `estimated_serving`
- `macros`: calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg
- `micros`: 11 vitamins (A/D/E/K/C/B1/B2/B3/B6/B12/folate) + 6 minerals (calcium/iron/magnesium/potassium/zinc/phosphorus)

All unknown values default to `0`. Code strips markdown fences as a fallback in case Gemini wraps output.

---

## Issues Fixed This Session

| Issue | Fix |
|---|---|
| Pillow failed to build on Windows | Removed from requirements — not needed (image bytes passed directly to Gemini) |
| `gemini-1.5-flash` model not found | Updated to `gemini-2.5-flash` (best available free model) |
| Quota exhausted error was cryptic | Added friendly "wait 60 seconds" message for HTTP 429 responses |
| Profile switch reloaded same page | `logout()` is now called before `navigate("/")` in TopBar so the route guard doesn't bounce back |
| `uvicorn` not in PATH on Windows | All scripts use `python -m uvicorn` instead |

---

## API Quick Reference

```
GET    /api/profiles              List all profiles
POST   /api/profiles              Create profile {name, pin, avatar_color}
POST   /api/profiles/verify       Verify PIN → returns profile or 401
DELETE /api/profiles/{id}         Soft-delete profile

POST   /api/meals/analyze         Upload image → AI nutrition analysis (no DB write)
POST   /api/meals/log             Save analyzed meal to DB
GET    /api/meals/timeline        ?profile_id&page&limit  — paginated meal history
GET    /api/meals/{id}            Full meal detail with macros + micros
DELETE /api/meals/{id}            Delete meal

GET    /api/nutrition/daily       ?profile_id&date        — today's totals
GET    /api/nutrition/monthly     ?profile_id&year&month  — monthly breakdown + averages

GET    /api/config                Check if API key is set
PUT    /api/config                Save {gemini_api_key}
```

Interactive API docs available at `http://localhost:8000/docs` while server is running.

---

## Macro/Micro Daily Reference Targets (used in UI progress bars)

| Nutrient | Goal |
|---|---|
| Calories | 2000 kcal |
| Protein | 150 g |
| Carbs | 250 g |
| Fat | 65 g |

Micros are displayed as raw values (no goal bars) — shown in a collapsible grid on each meal card.

---

## What's Not Built Yet (potential next steps)

- Custom daily calorie/macro goals per profile
- Edit meal nutrition values manually after logging
- Keep-image toggle in the Log Meal UI (backend supports it, frontend always sends `keep_image: false`)
- Push/export data (CSV, PDF report)
- Dark mode
