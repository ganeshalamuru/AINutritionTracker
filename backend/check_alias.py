"""Validate ONE food/dish name against the OFFLINE USDA index before editing an alias.

The companion to check_aliases.py (which audits the *whole* alias set against the live
FoodData Central **API**). This script checks a **single** name through the exact production
matching path — alias rewrite -> strict search -> simplified fallback -> the `_pick_best`
head-noun gate / best-of-N -> per-100g — but against the **offline** local FTS5 index
(usda_local.db), so it needs **no network, no USDA key, and no permission**: it's the
quick "what would the app pick for this name?" check to run before adding/changing an alias.

It runs both paths the app uses, so you see what actually happens:
  * DISH path - the dish-first FNDDS lookup (what a curated DISH_ALIASES entry resolves to).
  * INGREDIENT path - the decomposition lookup (what a FOOD_ALIASES entry / base item resolves to).

For each it prints the alias query used, the chosen match (description + dataType + cal/100g),
and the top raw candidates so a better alias can be chosen on a miss. Read-only.

Usage (from the backend/ directory):
    python check_alias.py "gulab jamun"
    python check_alias.py "mung beans"            # both paths
    python check_alias.py --dish "idli"           # dish path only
    python check_alias.py --food "okra"           # ingredient path only
"""

import logging
import sys

import services.usda_service as nd
from check_aliases import diagnose, diagnose_dish

# Force the OFFLINE backend: route _search_usda to the local FTS5 index, never the network.
nd._use_local = True

# Keep the table clean — silence the per-call request/response INFO logging.
logging.getLogger("nutriai.nutrition_db").setLevel(logging.WARNING)


def _print_result(label: str, name: str, q: str, chosen, candidates) -> None:
    via = "" if q == nd._normalize(name) else f"  (via '{q}')"
    print(f"\n=== {label} path: {name!r}{via} ===")
    if chosen is not None:
        per = nd._extract_per_100g(chosen)
        print(
            f"  PICKED -> {chosen.get('description')} "
            f"[{chosen.get('dataType')}] (~{per['calories']:.0f} cal/100g)"
        )
    else:
        print("  PICKED -> UNMATCHED (this name has no offline match)")
    if candidates:
        print("  candidates considered:")
        for c in candidates[:5]:
            print(f"    - {c.get('description')} [{c.get('dataType')}]")
    else:
        print("  candidates considered: (none)")


def main() -> None:
    args = sys.argv[1:]
    do_dish = do_food = True
    if args and args[0] in ("--dish", "--food"):
        do_dish = args[0] == "--dish"
        do_food = args[0] == "--food"
        args = args[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    name = " ".join(args).strip()
    if not nd.usda_local_search.is_available():
        print(
            f"Offline index missing at {nd.usda_local_search.DB_PATH} — run "
            "`python build_usda_db.py` first."
        )
        sys.exit(1)

    print(f"Validating {name!r} against the OFFLINE USDA index (no network, no key).")
    if do_dish:
        q, chosen, candidates = diagnose_dish(name)
        _print_result("DISH", name, q, chosen, candidates)
    if do_food:
        q, chosen, candidates = diagnose(name)
        _print_result("INGREDIENT", name, q, chosen, candidates)

    print(
        "\nNote: this is the OFFLINE index. After editing an alias, validate against the live API "
        "with `python check_aliases.py <key>` (ask first - it makes USDA API calls)."
    )


if __name__ == "__main__":
    main()
