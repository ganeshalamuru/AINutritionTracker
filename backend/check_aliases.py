"""Audit the USDA food + dish aliases against the real FoodData Central API.

Runs every entry in FOOD_ALIASES (plus a few common non-aliased foods) AND every entry
in DISH_ALIASES through the exact production matching path (alias -> strict search ->
simplified fallback -> head-noun gate / best-of-N) and prints what each resolves to. For
misses it also prints the raw candidates USDA returned, so a better alias can be chosen.

Use the DISH section to curate DISH_ALIASES: keep dishes that match in FNDDS; drop the
rest (they fall back to ingredient decomposition anyway).

Read-only (search calls only). The local cache is bypassed so results are always live.

Usage (from the backend/ directory):
    python check_aliases.py <USDA_API_KEY>
    python check_aliases.py                  # uses USDA_API_KEY env or backend/.env
"""
import logging
import os
import sys

import services.usda_service as nd

# Keep the table clean — silence the per-call request/response INFO logging.
logging.getLogger("nutriai.nutrition_db").setLevel(logging.WARNING)

# A few common foods NOT in the alias map, to exercise the plain (non-alias) path.
EXTRA_FOODS = [
    "spinach", "cucumber", "apple", "banana", "wheat flour",
    "idli", "vada", "poha", "upma", "curd rice",
]


def _load_key() -> str:
    if len(sys.argv) > 1 and sys.argv[1].strip():
        return sys.argv[1].strip()
    if os.getenv("USDA_API_KEY"):
        return os.environ["USDA_API_KEY"].strip()
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("USDA_API_KEY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    print("No USDA key. Pass it as an argument or set USDA_API_KEY (env or backend/.env).")
    sys.exit(1)


def diagnose(name: str, key: str):
    """Return (alias_query, chosen_food | None, candidate_foods) for one ingredient."""
    q = nd._aliased(name)
    foods = nd._search_usda(q, key, require_all=True)
    if not foods:
        simpler = nd._simplify(q)
        if simpler:
            loose = nd._search_usda(simpler, key, require_all=False)
            if loose:
                foods = loose
    return q, nd._pick_best(foods, q), foods


def diagnose_dish(name: str, key: str):
    """Like diagnose() but via the dish path: DISH_ALIASES + the dish data types."""
    q = nd.DISH_ALIASES.get(nd._normalize(name), nd._normalize(name))
    foods = nd._search_usda(q, key, require_all=True, data_types=nd.DISH_DATA_TYPES)
    if not foods:
        simpler = nd._simplify(q)
        if simpler:
            loose = nd._search_usda(simpler, key, require_all=False, data_types=nd.DISH_DATA_TYPES)
            if loose:
                foods = loose
    return q, nd._pick_best(foods, q), foods


def _audit(names, key, alias_of, diagnose_fn) -> list:
    """Run one audit pass; print each result and return the unmatched names.
    Raises UsdaRateLimitError so the caller can stop the whole run."""
    unmatched = []
    for name in names:
        alias = alias_of(name)
        via = "" if alias == name else f"  (via '{alias}')"
        try:
            q, chosen, candidates = diagnose_fn(name, key)
        except nd.UsdaRateLimitError:
            raise
        except Exception as e:
            print(f"MISS {name:22}{via}  | error: {type(e).__name__}: {e}")
            unmatched.append(name)
            continue

        if chosen is not None:
            per = nd._extract_per_100g(chosen)
            print(f"OK   {name:22}{via}  -> {chosen.get('description')} "
                  f"[{chosen.get('dataType')}] (~{per['calories']:.0f} cal/100g)")
        else:
            unmatched.append(name)
            print(f"MISS {name:22}{via}  -> UNMATCHED")
            for c in candidates[:3]:
                print(f"        candidate: {c.get('description')} [{c.get('dataType')}]")
            if not candidates:
                print("        candidate: (no results)")
    return unmatched


def main():
    key = _load_key()
    food_names = sorted(set(nd.FOOD_ALIASES) | set(EXTRA_FOODS))
    dish_names = sorted(set(nd.DISH_ALIASES))

    try:
        print(f"=== INGREDIENTS: auditing {len(food_names)} foods (ingredient path) ===\n")
        food_unmatched = _audit(food_names, key, nd._aliased, diagnose)

        print(f"\n=== DISHES: auditing {len(dish_names)} dishes (dish path, FNDDS) ===")
        print("(a MISS here is fine — that dish just falls back to ingredient decomposition)\n")
        dish_unmatched = _audit(
            dish_names, key,
            lambda n: nd.DISH_ALIASES.get(nd._normalize(n), nd._normalize(n)),
            diagnose_dish,
        )
    except nd.UsdaRateLimitError as e:
        print(f"\nRATE LIMITED - stopping. {e}")
        print("Wait an hour (or use a signed key with 1,000/hr) and re-run.")
        return

    print(f"\nIngredients: {len(food_names) - len(food_unmatched)} matched, "
          f"{len(food_unmatched)} unmatched.")
    if food_unmatched:
        print("  Unmatched: " + ", ".join(food_unmatched))
    print(f"Dishes: {len(dish_names) - len(dish_unmatched)} matched, "
          f"{len(dish_unmatched)} unmatched (these decompose to ingredients).")
    if dish_unmatched:
        print("  Unmatched: " + ", ".join(dish_unmatched))


if __name__ == "__main__":
    main()
