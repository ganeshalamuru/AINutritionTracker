"""Unit tests for the USDA nutrient-lookup stage (services/usda_service.py).

No network: every external USDA call is stubbed via the shared `nd._SESSION.post`. The
cache is pointed at a throwaway temp SQLite DB so tests never touch the real nutrition.db.

Run from the backend/ directory:
    python -m unittest tests.test_usda_service
    python -m unittest discover -s tests        # all tests
"""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine

import services.usda_service as nd


class FakeResp:
    """Minimal stand-in for a requests.Response."""
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code != 200:
            raise Exception(f"HTTP {self.status_code}")


def food(data_type, desc, fdc_id, nutrients=None, score=0):
    """Build a USDA search-result food record."""
    return {
        "dataType": data_type,
        "description": desc,
        "fdcId": fdc_id,
        "score": score,
        "foodNutrients": [{"nutrientId": nid, "value": v} for nid, v in (nutrients or {}).items()],
    }


class NutritionDbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Isolate the cache in a temp DB (see feedback: never write tests to the live DB).
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        cls._engine = create_engine(f"sqlite:///{cls._tmp.name}", connect_args={"check_same_thread": False})

    @classmethod
    def tearDownClass(cls):
        cls._engine.dispose()
        os.unlink(cls._tmp.name)

    def setUp(self):
        # Redirect the module's cache engine to the temp DB and reset the table flag.
        self._engine_patch = patch.object(nd, "engine", self._engine)
        self._engine_patch.start()
        nd._cache_ready = False
        os.environ.pop("MOCK_GEMINI", None)
        with self._engine.begin() as c:
            from sqlalchemy import text
            nd._ensure_cache_table()
            c.execute(text("DELETE FROM food_cache"))

    def tearDown(self):
        self._engine_patch.stop()

    # --- query simplification ---

    def test_simplify_strips_qualifier_and_adjective(self):
        self.assertEqual(nd._simplify("onion, fried"), "onion")
        self.assertEqual(nd._simplify("chicken breast, cooked"), "chicken breast")

    def test_simplify_returns_empty_when_nothing_to_simplify(self):
        self.assertEqual(nd._simplify("yogurt"), "")
        self.assertEqual(nd._simplify("basmati rice"), "")

    # --- best-of-N selection ---

    def test_pick_best_prefers_generic_over_breaded_fndds(self):
        foods = [
            food("Survey (FNDDS)", "Chicken breast tenders, breaded, cooked", 1, score=900),
            food("SR Legacy", "Chicken, broiler, breast, meat only, cooked", 2, score=100),
        ]
        self.assertEqual(nd._pick_best(foods, "chicken breast cooked")["fdcId"], 2)

    def test_pick_best_empty(self):
        self.assertIsNone(nd._pick_best([], "anything"))

    # --- nutrient extraction / scaling ---

    def test_extract_per_100g_maps_ids_and_energy_fallback(self):
        per = nd._extract_per_100g(food("SR Legacy", "X", 1, {1003: 20, 2047: 250}))
        self.assertEqual(per["protein_g"], 20)
        self.assertEqual(per["calories"], 250)  # Atwater fallback when 1008 absent

    # --- query construction / aliasing ---

    def test_alias_rewrites_search_query(self):
        calls = []
        hit = food("Foundation", "Rice, white, cooked", 1, {1008: 130})

        def post(url, params=None, json=None, timeout=None):
            calls.append((json["query"], json["requireAllWords"]))
            return FakeResp(200, {"foods": [hit]})

        with patch.object(nd._SESSION, "post", side_effect=post):
            nd.lookup_nutrients("basmati rice", "key")
        # 'basmati rice' is aliased to the generic cooked-rice query, sent strict.
        self.assertEqual(calls, [("rice white cooked", True)])

    def test_base_ingredient_aliases(self):
        # Dish-decomposition base ingredients map to USDA-friendly generic queries.
        self.assertEqual(nd._aliased("toor dal"), "pigeon peas cooked")
        self.assertEqual(nd._aliased("urad dal"), "lentils cooked")  # USDA has no urad
        self.assertEqual(nd._aliased("filter coffee"), "brewed coffee")
        self.assertEqual(nd._aliased("coconut"), "coconut raw")
        self.assertEqual(nd._aliased("carrot"), "carrots raw")
        self.assertEqual(nd._aliased("apple"), "apples raw")
        self.assertEqual(nd._aliased("banana"), "bananas raw")

    def test_prefers_candidate_with_energy(self):
        # A 0-calorie record (missing energy data) loses to a populated one even
        # when it would otherwise rank higher (e.g. preferred data type).
        cands = [
            food("Foundation", "Butter, stick, salted", 1, {1003: 0.9}),       # no energy
            food("SR Legacy", "Butter, salted", 2, {1008: 717, 1004: 81}),     # populated
        ]

        def post(url, params=None, json=None, timeout=None):
            return FakeResp(200, {"foods": cands})

        with patch.object(nd._SESSION, "post", side_effect=post):
            per = nd.lookup_nutrients("butter", "key")
        self.assertEqual(per["calories"], 717)

    def test_lookup_picks_best_and_caches(self):
        hit = food("SR Legacy", "Onions, raw", 11, {1008: 40, 1089: 0.2})

        def post(url, params=None, json=None, timeout=None):
            return FakeResp(200, {"foods": [hit]})

        with patch.object(nd._SESSION, "post", side_effect=post) as m:
            per = nd.lookup_nutrients("onion", "key")
            self.assertEqual(per["calories"], 40)
            # second call served from cache -> no extra POST
            nd.lookup_nutrients("onion", "key")
            self.assertEqual(m.call_count, 1)

    def test_simplified_fallback_relaxes_require_all_words(self):
        # 'salmon, grilled' isn't aliased -> primary strict miss, then lenient retry.
        calls = []
        hit = food("SR Legacy", "Fish, salmon, cooked", 9, {1008: 200})

        def post(url, params=None, json=None, timeout=None):
            calls.append((json["query"], json["requireAllWords"]))
            return FakeResp(200, {"foods": [hit]} if json["query"] == "salmon" else {"foods": []})

        with patch.object(nd._SESSION, "post", side_effect=post):
            per = nd.lookup_nutrients("salmon, grilled", "key")
        self.assertEqual(calls, [("salmon, grilled", True), ("salmon", False)])
        self.assertEqual(per["calories"], 200)

    def test_head_noun_gate_rejects_unrelated_results(self):
        # 'mint leaves' -> alias 'spearmint fresh'; USDA returns only other greens.
        greens = [
            food("SR Legacy", "Amaranth leaves, raw", 1, {1008: 23}),
            food("SR Legacy", "Broccoli, leaves, raw", 2, {1008: 28}),
        ]

        def post(url, params=None, json=None, timeout=None):
            return FakeResp(200, {"foods": greens})

        with patch.object(nd._SESSION, "post", side_effect=post):
            self.assertIsNone(nd.lookup_nutrients("mint leaves", "key"))

    def test_first_word_ranking_beats_data_type(self):
        # 'yogurt' alias 'yogurt plain whole': generic Yogurt (FNDDS) should beat
        # 'Tofu yogurt' (SR Legacy) because the food noun is the first word.
        foods = [
            food("SR Legacy", "Tofu yogurt", 1, {1008: 94}),
            food("Survey (FNDDS)", "Yogurt, plain, whole milk", 2, {1008: 61}),
        ]

        def post(url, params=None, json=None, timeout=None):
            return FakeResp(200, {"foods": foods})

        with patch.object(nd._SESSION, "post", side_effect=post):
            per = nd.lookup_nutrients("yogurt", "key")
        self.assertEqual(per["calories"], 61)

    def test_plural_stem_match(self):
        hit = food("SR Legacy", "Onions, cooked, boiled", 11, {1008: 44})

        def post(url, params=None, json=None, timeout=None):
            return FakeResp(200, {"foods": [hit]})

        with patch.object(nd._SESSION, "post", side_effect=post):
            # alias 'onions cooked' -> noun 'onions' (stem 'onion') matches 'Onions'
            self.assertIsNotNone(nd.lookup_nutrients("onion", "key"))

    def test_genuine_miss_returns_none(self):
        def post(url, params=None, json=None, timeout=None):
            return FakeResp(200, {"foods": []})

        with patch.object(nd._SESSION, "post", side_effect=post):
            self.assertIsNone(nd.lookup_nutrients("nonexistent food", "key"))

    # --- negative caching: a definitive miss is remembered, a timeout is not ---

    def test_miss_is_negative_cached(self):
        # A 0-hit search is remembered so a repeat lookup makes no further API call.
        with patch.object(nd._SESSION, "post",
                          side_effect=lambda *a, **k: FakeResp(200, {"foods": []})) as m:
            self.assertIsNone(nd.lookup_nutrients("nonexistent food", "key"))
            self.assertIsNone(nd.lookup_nutrients("nonexistent food", "key"))  # served from miss cache
        self.assertEqual(m.call_count, 1)

    def test_timeout_is_not_cached(self):
        # A transient timeout must NOT be remembered as a miss — the next lookup retries
        # and can succeed once USDA responds.
        with patch.object(nd._SESSION, "post", side_effect=nd.requests.exceptions.Timeout()):
            self.assertIsNone(nd.lookup_nutrients("onion", "key"))
        hit = food("SR Legacy", "Onions, raw", 1, {1008: 40})
        with patch.object(nd._SESSION, "post",
                          side_effect=lambda *a, **k: FakeResp(200, {"foods": [hit]})) as m:
            per = nd.lookup_nutrients("onion", "key")  # retried, not blocked by a cached miss
        self.assertEqual(per["calories"], 40)
        self.assertGreaterEqual(m.call_count, 1)

    def test_dish_miss_is_negative_cached(self):
        # A curated dish that returns 0 dish hits is remembered; a second meal with the
        # same dish does no dish search at all.
        dish_searches = []

        def post(url, params=None, json=None, timeout=None):
            if json["dataType"] == nd.DISH_DATA_TYPES:
                dish_searches.append(json["query"])
                return FakeResp(200, {"foods": []})
            return FakeResp(200, {"foods": []})  # ingredients also miss (irrelevant here)

        dishes = [{"name": "dal", "grams": 100, "items": [{"food": "lentils", "grams": 100}]}]
        with patch.object(nd._SESSION, "post", side_effect=post):
            nd.nutrients_for_meal(dishes, "key")
            self.assertEqual(dish_searches, ["dal"])          # looked up once
            nd.nutrients_for_meal(dishes, "key")              # second meal, same dish
        self.assertEqual(dish_searches, ["dal"])              # still 1 -> served from miss cache

    def test_clear_cache_empties_table(self):
        hit = food("SR Legacy", "Rice, white, cooked", 1, {1008: 130})
        with patch.object(nd._SESSION, "post", side_effect=lambda *a, **k: FakeResp(200, {"foods": [hit]})) as m:
            nd.lookup_nutrients("rice", "key")
            nd.clear_cache()
            nd.lookup_nutrients("rice", "key")  # cache empty -> hits API again
            self.assertEqual(m.call_count, 2)

    # --- rate limit must be loud, not silent ---

    def test_rate_limit_raises(self):
        def post(url, params=None, json=None, timeout=None):
            return FakeResp(429, {"error": {"code": "OVER_RATE_LIMIT", "message": "x"}})

        with patch.object(nd._SESSION, "post", side_effect=post):
            with self.assertRaises(nd.UsdaRateLimitError):
                nd.lookup_nutrients("anything", "key")

    def test_rate_limit_propagates_through_nutrients_for_meal(self):
        def post(url, params=None, json=None, timeout=None):
            return FakeResp(429, {"error": {"code": "OVER_RATE_LIMIT"}})

        dishes = [{"name": "rice bowl", "grams": 100, "items": [{"food": "rice", "grams": 100}]}]
        with patch.object(nd._SESSION, "post", side_effect=post):
            with self.assertRaises(nd.UsdaRateLimitError):
                nd.nutrients_for_meal(dishes, "key")

    # --- ingredient summation (the decomposition / fallback path) ---

    def test_sum_ingredients_scales_dedupes_and_reports_unmatched(self):
        rice = food("SR Legacy", "Rice, white, cooked", 1, {1008: 100, 1089: 1.0})

        def post(url, params=None, json=None, timeout=None):
            q = json["query"]
            return FakeResp(200, {"foods": [rice]} if "rice" in q else {"foods": []})

        items = [
            {"food": "white rice, cooked", "grams": 200},  # 2x per-100g
            {"food": "white rice, cooked", "grams": 50},   # deduped name, +0.5x
            {"food": "mystery sauce", "grams": 30},         # unmatched
        ]
        with patch.object(nd._SESSION, "post", side_effect=post):
            totals, unmatched, skipped, lines = nd._sum_ingredients(items, "key", 8)

        self.assertAlmostEqual(totals["calories"], 250.0)   # (200+50)/100 * 100
        self.assertAlmostEqual(totals["iron_mg"], 2.5)      # (200+50)/100 * 1.0
        self.assertEqual(unmatched, ["mystery sauce"])
        self.assertEqual(skipped, [])
        # one breakdown line per valid ingredient (dupes preserved), all "ingredient"
        self.assertEqual([(l["food"], l["source"]) for l in lines], [
            ("white rice, cooked", "ingredient"),
            ("white rice, cooked", "ingredient"),
            ("mystery sauce", "ingredient"),
        ])

    # --- dish-first behaviour ---

    def test_dish_first_uses_dish_nutrients_not_ingredient_sum(self):
        # idli matches at the dish level (FNDDS) -> its ingredients are NOT looked up.
        ingredient_queries = []

        def post(url, params=None, json=None, timeout=None):
            q = json["query"]
            if json["dataType"] == nd.DISH_DATA_TYPES:           # dish search
                if "idli" in q:
                    return FakeResp(200, {"foods": [food("Survey (FNDDS)", "Idli", 1, {1008: 150})]})
                return FakeResp(200, {"foods": []})
            ingredient_queries.append(q)                          # ingredient fallback
            return FakeResp(200, {"foods": [food("SR Legacy", q, 2, {1008: 999})]})

        dishes = [{"name": "idli", "grams": 160,
                   "items": [{"food": "rice", "grams": 90}, {"food": "urad dal", "grams": 30}]}]
        with patch.object(nd._SESSION, "post", side_effect=post):
            macros, micros, unmatched, skipped, dishes_out = nd.nutrients_for_meal(dishes, "key")

        self.assertAlmostEqual(macros["calories"], 240.0)  # 150 * 160/100, NOT rice+urad
        self.assertEqual(unmatched, [])
        self.assertEqual(skipped, [])
        # matched dish -> name highlighted, ingredients carried but not looked up
        self.assertEqual(dishes_out, [{
            "name": "idli", "grams": 160, "matched": True,
            "ingredients": [
                {"food": "rice", "grams": 90, "status": "not_looked_up"},
                {"food": "urad dal", "grams": 30, "status": "not_looked_up"},
            ],
        }])
        self.assertEqual(ingredient_queries, [])  # fallback never ran

    def test_curated_dish_miss_falls_back_to_ingredients(self):
        # 'dal' is curated (in DISH_ALIASES) so it IS looked up at the dish level; when
        # that misses it decomposes to its ingredients.
        dish_searched = []

        def post(url, params=None, json=None, timeout=None):
            q = json["query"]
            if json["dataType"] == nd.DISH_DATA_TYPES:           # curated dish search, no match
                dish_searched.append(q)
                return FakeResp(200, {"foods": []})
            if "rice" in q:                                       # ingredient fallback
                return FakeResp(200, {"foods": [food("SR Legacy", "Rice, white, cooked", 1, {1008: 130})]})
            return FakeResp(200, {"foods": []})

        dishes = [{"name": "dal", "grams": 100,
                   "items": [{"food": "rice", "grams": 200}, {"food": "secret spice", "grams": 5}]}]
        with patch.object(nd._SESSION, "post", side_effect=post):
            macros, micros, unmatched, skipped, dishes_out = nd.nutrients_for_meal(dishes, "key")

        self.assertEqual(dish_searched, ["dal"])             # curated -> dish lookup attempted
        self.assertAlmostEqual(macros["calories"], 260.0)    # rice 130 * 200/100
        self.assertEqual(unmatched, ["secret spice"])
        self.assertEqual(skipped, [])
        # dish missed -> not matched, each ingredient carries its own USDA outcome
        self.assertEqual(dishes_out, [{
            "name": "dal", "grams": 100, "matched": False,
            "ingredients": [
                {"food": "rice", "grams": 200, "status": "matched"},
                {"food": "secret spice", "grams": 5, "status": "unmatched"},
            ],
        }])

    def test_uncurated_dish_skips_dish_lookup(self):
        # A dish name not in DISH_ALIASES gets NO speculative whole-dish lookup; it
        # decomposes straight to ingredients (saves a slow, almost-always-missing call).
        dish_searches = []

        def post(url, params=None, json=None, timeout=None):
            if json["dataType"] == nd.DISH_DATA_TYPES:
                dish_searches.append(json["query"])
            if "rice" in json["query"]:
                return FakeResp(200, {"foods": [food("SR Legacy", "Rice, white, cooked", 1, {1008: 130})]})
            return FakeResp(200, {"foods": []})

        dishes = [{"name": "mystery dish", "grams": 100,
                   "items": [{"food": "rice", "grams": 200}, {"food": "secret spice", "grams": 5}]}]
        with patch.object(nd._SESSION, "post", side_effect=post):
            macros, micros, unmatched, skipped, dishes_out = nd.nutrients_for_meal(dishes, "key")

        self.assertEqual(dish_searches, [])                  # no dish-level lookup attempted
        self.assertAlmostEqual(macros["calories"], 260.0)    # decomposed: rice 130 * 200/100
        self.assertEqual(unmatched, ["secret spice"])
        self.assertEqual(dishes_out[0]["matched"], False)

    # --- transient-failure retries ---

    def test_search_retries_on_timeout_then_succeeds(self):
        hit = food("SR Legacy", "Onions, raw", 1, {1008: 40})
        with patch.object(nd._SESSION, "post",
                          side_effect=[nd.requests.exceptions.Timeout(), FakeResp(200, {"foods": [hit]})]) as m:
            per = nd.lookup_nutrients("onion", "key")
        self.assertEqual(m.call_count, 2)                    # retried once, then succeeded
        self.assertIsNotNone(per)
        self.assertEqual(per["calories"], 40)

    def test_search_exhausts_retries_returns_none(self):
        with patch.object(nd._SESSION, "post",
                          side_effect=nd.requests.exceptions.Timeout()) as m:
            self.assertIsNone(nd.lookup_nutrients("onion", "key"))
        self.assertEqual(m.call_count, nd.USDA_RETRIES + 1)  # all attempts timed out

    def test_mock_mode_returns_canned_totals_without_network(self):
        os.environ["MOCK_GEMINI"] = "1"
        try:
            # requests.post is NOT patched — a network call here would error/hang.
            dishes = [{"name": "idli", "grams": 160, "items": [{"food": "rice", "grams": 90}]}]
            macros, micros, unmatched, skipped, dishes_out = nd.nutrients_for_meal(dishes, "key")
        finally:
            os.environ.pop("MOCK_GEMINI", None)
        self.assertEqual(macros["calories"], nd.MOCK_MACROS["calories"])
        self.assertEqual(unmatched, [])
        self.assertEqual(skipped, [])
        self.assertEqual(dishes_out, [{
            "name": "idli", "grams": 160, "matched": True,
            "ingredients": [{"food": "rice", "grams": 90, "status": "not_looked_up"}],
        }])

    # --- spices: model wording -> USDA wording ---

    def test_spice_aliases_match_usda_wording(self):
        self.assertEqual(nd._aliased("turmeric powder"), "turmeric ground")
        self.assertEqual(nd._aliased("red chili powder"), "chili powder")
        self.assertEqual(nd._aliased("cumin powder"), "cumin seed")
        self.assertEqual(nd._aliased("cinnamon stick"), "cinnamon ground")

        hit = food("SR Legacy", "Spices, turmeric, ground", 1, {1008: 312, 1089: 55})
        with patch.object(nd._SESSION, "post", side_effect=lambda *a, **k: FakeResp(200, {"foods": [hit]})):
            per = nd.lookup_nutrients("turmeric powder", "key")
        self.assertIsNotNone(per)
        self.assertEqual(per["calories"], 312)

    def test_simplify_strips_descriptor_words(self):
        # Un-aliased "<food> powder/stick" still retries loosely on the bare food.
        self.assertEqual(nd._simplify("paprika powder"), "paprika")
        self.assertEqual(nd._simplify("lemongrass stick"), "lemongrass")

    # --- per-meal lookup cap ---

    def test_lookup_cap_skips_smallest_uncached(self):
        # Echo each query back as the description (noun present, energy populated).
        calls = []

        def post(url, params=None, json=None, timeout=None):
            q = json["query"]
            calls.append(q)
            return FakeResp(200, {"foods": [food("SR Legacy", q, 1, {1008: 100})]})

        items = [
            {"food": "alpha", "grams": 300},
            {"food": "beta", "grams": 200},
            {"food": "gamma", "grams": 10},   # smallest -> dropped when budget=2
        ]
        with patch.object(nd._SESSION, "post", side_effect=post) as m:
            totals, unmatched, skipped, lines = nd._sum_ingredients(items, "key", 2)

        self.assertEqual(skipped, ["gamma"])
        self.assertEqual(unmatched, [])
        self.assertEqual(m.call_count, 2)                 # only the two kept foods
        self.assertAlmostEqual(totals["calories"], 500.0)  # (300+200)/100 * 100, gamma excluded
        # a breakdown line is still emitted for the skipped ingredient (greyed in the UI)
        self.assertEqual([l["food"] for l in lines], ["alpha", "beta", "gamma"])

    def test_cached_lookups_are_free_and_dont_use_the_budget(self):
        def post(url, params=None, json=None, timeout=None):
            q = json["query"]
            if "rice" in q:
                return FakeResp(200, {"foods": [food("SR Legacy", "Rice, white, cooked", 1, {1008: 130})]})
            return FakeResp(200, {"foods": [food("SR Legacy", q, 2, {1008: 100})]})

        with patch.object(nd._SESSION, "post", side_effect=post):
            nd.lookup_nutrients("rice", "key")   # pre-cache "rice"
            items = [
                {"food": "rice", "grams": 100},    # cached -> free, always counted
                {"food": "alpha", "grams": 300},   # largest uncached -> looked up
                {"food": "beta", "grams": 200},    # over the budget -> skipped
            ]
            totals, unmatched, skipped, lines = nd._sum_ingredients(items, "key", 1)

        self.assertEqual(skipped, ["beta"])
        self.assertAlmostEqual(totals["calories"], 430.0)  # rice 130 + alpha 300, beta excluded


if __name__ == "__main__":
    unittest.main()
