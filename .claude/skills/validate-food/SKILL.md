---
name: validate-food
description: Validate a food/dish name against the offline USDA index BEFORE adding or changing a FOOD_ALIASES / DISH_ALIASES entry. Shows what the production matching path would pick (description + cal/100g + candidates), then waits for approval before editing. Use whenever an alias, dish proxy, or nutrient mapping is being added or changed.
---

# validate-food

Ground every alias/curation change in real USDA data **before** writing code. This is the
project's top friction point: aliases that *match but resolve to the wrong variant* (e.g. bare
"mung beans" landing the sprouted, canned ~12 cal entry instead of plain cooked ~105). Validate
first, show the evidence, get an OK, then edit.

**Never edit `FOOD_ALIASES` / `DISH_ALIASES` (or a dish proxy / nutrient mapping) before
completing step 1 and getting the user's explicit approval in step 3.**

## Steps

1. **Validate against the OFFLINE index** (read-only, no network, no key, no permission needed).
   From `backend/`:
   ```
   python check_alias.py "<name>"            # both the dish and ingredient paths
   python check_alias.py --dish "<name>"     # dish-first FNDDS path only
   python check_alias.py --food "<name>"     # decomposition / ingredient path only
   ```
   This runs the **exact production matching path** (alias rewrite -> search -> simplify fallback
   -> the `_pick_best` head-noun gate -> per-100g) against `usda_local.db`, so it shows what the
   app would actually pick — not just raw search hits. To explore raw candidates more widely (to
   *choose* a better alias value), query the offline DB directly via the `sqlite-usda` MCP
   (`foods` / `food_nutrients` tables) — read-only.

2. **Read the result like the README's curation rule.** A match is only good if the chosen
   description is the right *variant* on calories (the head-noun gate puts the distinctive food
   word last). Confirm cal/100g is plausible for the real food. A dish MISS is fine — that dish
   just falls back to ingredient decomposition; only curate `DISH_ALIASES` for dishes FNDDS
   actually carries.

3. **Show the user the candidate match(es) and the proposed alias mapping, then STOP and wait for
   approval.** Present: the name, what it resolves to today, your proposed alias value, and what
   *that* resolves to (run `check_alias.py` on the proposed value too). Do not edit until the user
   confirms.

4. **Edit the alias** in `backend/services/nutrition_data/aliases.py`. Curate the value so the
   distinctive food word lands **last** (the `_food_noun` gate). Drop `DISH_ALIASES` entries that
   don't match FNDDS — they only waste a speculative call.

5. **Validate the live API path** with `python check_aliases.py <key>` (the full audit against the
   real FoodData Central API). **This makes USDA API calls — ask the user before running it**
   (per `CLAUDE.md`: no USDA probes without permission). The offline check in step 1 is enough to
   propose a change; this confirms the online backend agrees before shipping.

6. **Bump `CACHE_VERSION`** in `backend/core/config.py` so cached misses for the now-resolvable
   name are purged on next startup (don't wipe `food_cache` manually). Then hand off to the
   `commit` skill (lint + tests + commit).

## Finding what to curate

`python list_misses.py` (from `backend/`) prints the negative-cached names real meals failed to
match — the curation worklist, split offline/online. Read-only. Start there, validate each
candidate with `check_alias.py`, then follow the steps above.

## Rules

- Offline `check_alias.py` / `list_misses.py` / `sqlite-usda` MCP queries are free and need no
  permission. The **online** `check_aliases.py` audit hits the USDA API — always ask first.
- Validate the *proposed alias value*, not just the original name — that's the whole point.
- Prefer the simplest change; one alias entry per real miss. Don't add speculative aliases for
  names that already resolve correctly.
