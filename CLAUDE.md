# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Permissions / Boundaries

- Never run external probes, USDA API calls, or expensive network operations without explicit user permission first.
- Don't run expensive *local* operations (e.g. Ollama inference — especially the 8B model, which offloads to CPU and takes ~40s/photo) without first calling out the scope and cost. Even with general permission to "test locally", state exactly what will run (which models, how many calls, rough time) and let the user confirm before launching — don't quietly include the heavy 8B when the user expected only the 4B.

## Testing / Commit Workflow

- Always verify changes against passing tests and run a build/smoke test before committing; commit only after the user's stated goals are verified.

## Domain Rules / Nutrition Data

- Validate all food/dish nutrient data against actual USDA/FNDDS data before implementing aliases or normalization logic.

## Safety / Destructive Operations

- Never wipe or clear the live `food_cache` table to force re-resolution. Bump `CACHE_VERSION` in `core/config.py` instead — the lifespan purges the cache on a version change. Likewise never delete/overwrite the live `nutrition.db` (or PUT test data to the running app) to test; use a temp DB (see `backend/tests`).
- Review `ruff --fix` / F401 autofixes before applying — they have stripped intentional re-exports (e.g. `CACHE_VERSION`) and crashed startup. The post-edit hook deliberately runs `ruff check` *without* `--fix`; when you do run `--fix`, eyeball the diff for removed re-exports.
- Pause and confirm before any destructive (DB wipe, mass autofix) or expensive (heavy local-model run, USDA API probe) action, and propose a non-destructive alternative first.

## Codebase Navigation

- When a README or pointer doc exists, read it first instead of broadly exploring the codebase.

## Environment / Platform

- Development happens on Windows; the app is pivoting from local-first toward deployment as a Linux container (Docker). Keep changes portable across both: don't hardcode Windows-only paths/commands or assume a local-only runtime.
- On the Windows dev side: verify CLI tools (e.g. uv) are installed as PATH executables and watch for em-dash/mojibake encoding issues.
- Prefer epoch-integer timestamps to avoid SQLite timezone bugs (matters on both Windows dev and the Linux deploy target).
