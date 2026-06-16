# Audit findings — 2026-06-16

Open items from a read-only codebase audit (FastAPI best practices + USDA alias
mis-resolutions). This is a transient worklist, not architecture docs — the README remains the
single source of truth. Delete entries as they're fixed; delete the file when empty.

**Verification status:** Area 2 alias items were validated against the offline `usda_local.db`
through the real matching pipeline (`_aliased` → `_search_usda` → `_pick_best`). Area 1 items are
audit observations that are **not yet runtime-verified** — confirm each against the running app /
a test before fixing.

## Resolved this session (for context)
- ~~`pulao`/`vegetable pulao` → "fried rice" landed "Rice bowl with chicken, frozen entree"
  (~126 cal) — a chicken dish for a veg meal.~~ **Fixed:** aliased to `"rice fried meatless"` so the
  gate keeps "Rice, fried, meatless" [FNDDS] (~174 cal/100g). Verified offline.
- ~~P0 "`except ValueError, TypeError:` crashes startup" — **false positive.** Valid Python 3.14
  syntax (PEP 758, bracketless except); compiles and catches both. See memory
  `reference-py314-bracketless-except`.~~

## Area 1 — FastAPI / backend (NOT yet runtime-verified)

- **P1** `services/meal_service.py:70-80` — temp-image `open()/write()` runs synchronously on the
  async `analyze_image` coroutine (Stage-1/2 calls are correctly off-thread; this write isn't).
  Direction: offload the write, or write inside the worker thread.
- **P1** `services/meal_service.py:79` — unguarded `os.remove(temp_path)` on the failure path could
  raise `FileNotFoundError` and mask the original vision error. Direction: guard cleanup like
  `_cleanup_temp` already does.
- **P1** `main.py:202` catch-all `serve_react` — unknown `/api/...` paths fall through to the SPA
  shell (200 HTML) instead of a JSON 404. Direction: scope the catch-all to non-`/api` paths.
- **P2** `core/database.py:4` — `DATABASE_URL = "sqlite:///./nutrition.db"` is CWD-relative while
  everything else anchors to `BACKEND_DIR`; fragile, and relevant to the Linux-container deploy
  pivot. Direction: anchor the SQLite path to `BACKEND_DIR`.
- **P2** `main.py` access-log middleware — failed requests skip the access-log line (only the
  exception handler logs). Direction: emit the access line in a `finally`.

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
