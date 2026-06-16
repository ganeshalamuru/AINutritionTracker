# Audit findings — 2026-06-16

Open items from a read-only codebase audit (FastAPI best practices + USDA alias
mis-resolutions). This is a transient worklist, not architecture docs — the README remains the
single source of truth. Delete entries as they're fixed; delete the file when empty.

**Verification status:** Area 2 alias items were validated against the offline `usda_local.db`
through the real matching pipeline (`_aliased` → `_search_usda` → `_pick_best`). All Area 1
(FastAPI/backend) items have been fixed and verified (75 tests pass incl. a new routing test,
ruff clean, DB-path smoke check); only the Area 2 low-priority notes remain.

## Resolved this session (for context)
- ~~`pulao`/`vegetable pulao` → "fried rice" landed "Rice bowl with chicken, frozen entree"
  (~126 cal) — a chicken dish for a veg meal.~~ **Fixed:** aliased to `"rice fried meatless"` so the
  gate keeps "Rice, fried, meatless" [FNDDS] (~174 cal/100g). Verified offline.
- ~~P0 "`except ValueError, TypeError:` crashes startup" — **false positive.** Valid Python 3.14
  syntax (PEP 758, bracketless except); compiles and catches both. See memory
  `reference-py314-bracketless-except`.~~
- ~~**Area 1 — FastAPI / backend (5 items).**~~ **All fixed:** (1) temp-image write offloaded via
  `asyncio.to_thread` + (2) failure-path cleanup guarded by a shared `_remove_temp` helper
  (`meal_service.py`); (3) unknown `/api/...` paths now return a JSON 404 instead of the SPA shell +
  (5) the access-log line moved into `finally` so failed requests are logged (`main.py`);
  (4) `DATABASE_URL` anchored to `BACKEND_DIR` instead of CWD (`core/database.py`).

## Area 2 — USDA aliases (validated offline; mostly fine)

Most flagged aliases resolve **correctly** despite "food noun not last" (the gate still lands the
right food when candidates are homogeneous): `bell pepper`, `black pepper`, `coriander`/`cilantro`
(no collision with `coriander powder`), `onion`, `mint`, `jaggery`/`gur`/`sugar`, `dal` (FNDDS has a
"Dal" entry, ~145 cal — not a wasted lookup), `roti`/`chapati`/`naan`, `jalebi`, `gulab jamun`.
No action needed on those.

Remaining low-priority notes (not bugs):
- **P3** `fish` → "fish cooked" lands "Fish, pollock, Alaska, cooked" (~87) — reasonable generic,
  though "Fish, cooked, as ingredient" [FNDDS] exists if a more neutral entry is wanted.
- **P3** `raisins` → "Raisins, seeded" (~296) vs plain "Raisins" [FNDDS] — negligible calorie diff.

**Meta-lesson for future alias work:** the real failure mode is NOT "food noun isn't last" — it's a
semantically-wrong candidate *passing* the head-noun gate and winning on data-type rank (the pulao
chicken-bowl case). When auditing aliases, check what `_pick_best` actually returns offline, not just
the token order.
