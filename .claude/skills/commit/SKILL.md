---
name: commit
description: Run tests + lint, sync the README if behavior changed, then stage and commit with a concise conventional-commit message. Use when the user asks to commit, ship, or wrap up a change. Will NOT commit if tests fail.
---

# commit

Verify the change, then commit it. **Do not commit if tests fail.**

## Steps

1. **Lint** (from `backend/`):
   ```
   uv run ruff check
   uv run ruff format --check
   ```
   Fix lint errors (`ruff check --fix`, `ruff format`) and re-run until clean. Do not strip
   intentional re-exports when autofixing.

2. **Test** (from `backend/`):
   ```
   uv run pytest
   ```
   If any test fails, **stop** — report the failure with output and do not commit.

3. **Build / smoke check** if the change touches the frontend or app boot — confirm the relevant
   build or startup still works before committing.

4. **Sync docs** — if behavior, flows, conventions, or the API changed, update `README.md` (the
   single source of truth) in the same commit. Skip if the change is behavior-neutral.

5. **Stage & commit** only the files relevant to this change. Use a concise
   [conventional-commit](https://www.conventionalcommits.org/) message (`feat:`, `fix:`, `docs:`,
   `refactor:`, `chore:`, `test:`) summarizing *what changed and why*. End the message with:
   ```
   Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
   ```

## Rules

- Commit **only after** lint + tests pass and the user's stated goals are verified.
- If on `main`/`master`, branch first unless the user said otherwise.
- Never use `--no-verify` or skip hooks; if a hook fails, fix the underlying issue.
- Don't run external probes / USDA API calls as part of verification (see `CLAUDE.md`).
