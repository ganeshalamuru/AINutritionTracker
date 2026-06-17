# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Permissions / Boundaries

- Never run external probes, USDA API calls, or expensive network operations without explicit user permission first.
- Don't run expensive *local* operations (e.g. Ollama inference — especially the 8B model, which offloads to CPU and takes ~40s/photo) without first calling out the scope and cost. Even with general permission to "test locally", state exactly what will run (which models, how many calls, rough time) and let the user confirm before launching — don't quietly include the heavy 8B when the user expected only the 4B.

## Testing / Commit Workflow

- Always verify changes against passing tests and run a build/smoke test before committing; commit only after the user's stated goals are verified.

## Domain Rules / Nutrition Data

- Validate all food/dish nutrient data against actual USDA/FNDDS data before implementing aliases or normalization logic.

## Codebase Navigation

- When a README or pointer doc exists, read it first instead of broadly exploring the codebase.

## Environment / Platform

- Development happens on Windows; the app is pivoting from local-first toward deployment as a Linux container (Docker). Keep changes portable across both: don't hardcode Windows-only paths/commands or assume a local-only runtime.
- On the Windows dev side: verify CLI tools (e.g. uv) are installed as PATH executables and watch for em-dash/mojibake encoding issues.
- Prefer epoch-integer timestamps to avoid SQLite timezone bugs (matters on both Windows dev and the Linux deploy target).
