"""List the food names that USDA matching couldn't resolve — the alias curation worklist.

Stage 2 negative-caches a definitive miss in `food_cache` (the row's `nutrients_json` is
the sentinel `{"__miss__": true}`), so every name a real meal failed to match is already
recorded. This script prints those names, deduped and sorted, split by backend (offline
keys are namespaced `local::`). Read-only.

Use the output to grow the curated tables: add the worthwhile names to FOOD_ALIASES (or
DISH_ALIASES if FNDDS carries the composite dish), validate with `python check_aliases.py
<key>`, then bump CACHE_VERSION in core/config.py so the cached misses are purged and the
names re-resolve.

Usage (from the backend/ directory):
    python list_misses.py
"""

import json

from sqlalchemy import text

from core.database import engine

_LOCAL_PREFIX = "local::"


def _misses() -> dict[str, list[str]]:
    """Return {"offline": [...], "online": [...]} of distinct missed names, sorted."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT query, nutrients_json FROM food_cache")).all()

    offline: set[str] = set()
    online: set[str] = set()
    for query, payload in rows:
        if not payload:
            continue
        try:
            if not json.loads(payload).get("__miss__"):
                continue
        except ValueError:  # bad/legacy JSON payload (JSONDecodeError ⊂ ValueError)
            continue
        if query.startswith(_LOCAL_PREFIX):
            offline.add(query[len(_LOCAL_PREFIX) :])
        else:
            online.add(query)
    return {"offline": sorted(offline), "online": sorted(online)}


def main() -> None:
    groups = _misses()
    total = sum(len(v) for v in groups.values())
    if not total:
        print("No cached misses — every looked-up name resolved (or the cache is empty).")
        return

    for backend, names in groups.items():
        if not names:
            continue
        print(f"\n{backend} backend — {len(names)} unresolved name(s):")
        for name in names:
            print(f"  {name}")

    print(f"\n{total} name(s) to curate. Add to FOOD_ALIASES / DISH_ALIASES, validate with")
    print("check_aliases.py, then bump CACHE_VERSION (core/config.py) to purge these misses.")


if __name__ == "__main__":
    main()
