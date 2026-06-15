"""Unit tests for the offline USDA search backend (services/usda_local_search.py) and its
integration with usda_service when nutrition_source = "offline".

No network and no real data: each test builds a tiny temp FTS5 DB (same schema as
build_usda_db.py) and points the module's DB_PATH at it. The usda_service integration test also
isolates the food cache in a throwaway SQLite DB (see test_db_isolation feedback).

Run from the backend/ directory:
    python -m unittest tests.test_usda_local_search
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, text

import services.usda_local_search as ls
import services.usda_service as nd


def _build_db(path: str, foods: list[tuple]):
    """foods: list of (fdc_id, description, data_type, {nutrient_id: amount})."""
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE foods (fdc_id INTEGER PRIMARY KEY, description TEXT, data_type TEXT);
        CREATE TABLE food_nutrients (fdc_id INTEGER, nutrient_id INTEGER, amount REAL);
        CREATE VIRTUAL TABLE foods_fts USING fts5(
            description, content='foods', content_rowid='fdc_id', tokenize='porter unicode61'
        );
        """
    )
    for fid, desc, dtype, nutrients in foods:
        conn.execute("INSERT INTO foods VALUES (?, ?, ?)", (fid, desc, dtype))
        conn.executemany(
            "INSERT INTO food_nutrients VALUES (?, ?, ?)",
            [(fid, nid, amt) for nid, amt in nutrients.items()],
        )
    conn.execute("INSERT INTO foods_fts (foods_fts) VALUES ('rebuild')")
    conn.commit()
    conn.close()


SAMPLE = [
    (1, "Rice, white, cooked, regular", "SR Legacy", {1008: 130, 1003: 2.7, 1005: 28}),
    (2, "Idli", "Survey (FNDDS)", {1008: 128, 1005: 25}),
    (3, "Snacks, rice cakes, brown rice", "SR Legacy", {1008: 387}),
]


class LocalSearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._tmp.close()
        _build_db(cls._tmp.name, SAMPLE)
        cls._patch = patch.object(ls, "DB_PATH", cls._tmp.name)
        cls._patch.start()

    @classmethod
    def tearDownClass(cls):
        cls._patch.stop()
        os.unlink(cls._tmp.name)

    def test_returns_usda_candidate_shape(self):
        foods = ls.search("rice")
        self.assertTrue(foods)
        f = foods[0]
        self.assertEqual(set(f), {"description", "dataType", "fdcId", "score", "foodNutrients"})
        self.assertTrue(all({"nutrientId", "value"} <= set(n) for n in f["foodNutrients"]))

    def test_extract_per_100g_consumes_a_result(self):
        # The candidate must be directly digestible by usda_service's extractor.
        rice = next(f for f in ls.search("rice cooked") if f["fdcId"] == 1)
        per = nd._extract_per_100g(rice)
        self.assertEqual(per["calories"], 130)
        self.assertEqual(per["carbs_g"], 28)

    def test_data_type_filter(self):
        self.assertEqual(
            [f["fdcId"] for f in ls.search("idli", data_types=["Survey (FNDDS)"])], [2]
        )
        self.assertEqual(ls.search("idli", data_types=["SR Legacy"]), [])

    def test_strict_requires_all_words_loose_does_not(self):
        # "rice cooked": only food 1 has both words; food 3 ("rice cakes") lacks "cooked".
        strict = {f["fdcId"] for f in ls.search("rice cooked", require_all=True)}
        loose = {f["fdcId"] for f in ls.search("rice cooked", require_all=False)}
        self.assertEqual(strict, {1})
        self.assertEqual(loose, {1, 3})

    def test_score_orders_better_match_higher(self):
        # score = -bm25, so the best (lowest bm25) candidate carries the highest score.
        foods = ls.search("rice")
        scores = [f["score"] for f in foods]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_query_returns_empty(self):
        self.assertEqual(ls.search("   "), [])

    def test_missing_db_returns_empty(self):
        with patch.object(ls, "DB_PATH", os.path.join(tempfile.gettempdir(), "nope_missing.db")):
            ls._warned_missing = False
            self.assertEqual(ls.search("rice"), [])


class OfflineIntegrationTest(unittest.TestCase):
    """usda_service routed through the offline backend resolves real per-100g profiles."""

    @classmethod
    def setUpClass(cls):
        cls._search_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._search_db.close()
        _build_db(cls._search_db.name, SAMPLE)
        cls._cache_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        cls._cache_db.close()
        cls._engine = create_engine(
            f"sqlite:///{cls._cache_db.name}", connect_args={"check_same_thread": False}
        )

    @classmethod
    def tearDownClass(cls):
        cls._engine.dispose()
        os.unlink(cls._search_db.name)
        os.unlink(cls._cache_db.name)

    def setUp(self):
        self._patches = [
            patch.object(ls, "DB_PATH", self._search_db.name),
            patch.object(nd, "engine", self._engine),
            patch.object(nd, "_use_local", True),
        ]
        for p in self._patches:
            p.start()
        nd._cache_ready = False
        nd._ensure_cache_table()
        with self._engine.begin() as c:
            c.execute(text("DELETE FROM food_cache"))

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_offline_ingredient_lookup(self):
        # "white rice, cooked" -> aliased/strict tokens present in "Rice, white, cooked, regular".
        per = nd.lookup_nutrients("white rice, cooked")
        self.assertIsNotNone(per)
        self.assertEqual(per["calories"], 130)

    def test_offline_dish_lookup(self):
        per = nd.lookup_dish("idli")
        self.assertIsNotNone(per)
        self.assertEqual(per["calories"], 128)

    def test_offline_miss_returns_none(self):
        self.assertIsNone(nd.lookup_nutrients("nonexistent food xyz"))

    def test_offline_cache_key_is_namespaced(self):
        # An offline lookup is stored under a 'local::'-prefixed key (so it can't collide with
        # an online result for the same name).
        nd.lookup_nutrients("white rice, cooked")
        with self._engine.connect() as c:
            keys = [r[0] for r in c.execute(text("SELECT query FROM food_cache")).fetchall()]
        self.assertTrue(any(k.startswith("local::") for k in keys), keys)


if __name__ == "__main__":
    unittest.main()
