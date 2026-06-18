"""Tests for the public foods API (routers/foods.py) over the offline USDA index.

No HTTP: builds a tiny usda_local.db (reusing the helper from test_usda_local_search) and calls
the router functions directly, asserting the FoodSummary/FoodDetail shapes and the 404/503 paths.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

import services.usda_local_search as ls
from routers import foods
from tests.test_usda_local_search import SAMPLE, _build_db


class FoodsApiTest(unittest.TestCase):
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

    def test_search_returns_summaries(self):
        hits = foods.search_foods(q="rice", data_type=None, require_all=True, limit=10)
        self.assertTrue(hits)
        self.assertTrue(all(h.fdc_id and h.description and h.data_type for h in hits))

    def test_search_data_type_filter(self):
        hits = foods.search_foods(q="idli", data_type="Survey (FNDDS)", require_all=True, limit=10)
        self.assertEqual([h.fdc_id for h in hits], [2])
        self.assertEqual(
            foods.search_foods(q="idli", data_type="SR Legacy", require_all=True, limit=10), []
        )

    def test_get_food_returns_detail_with_nutrients(self):
        detail = foods.get_food(1)  # Rice, white, cooked, regular
        self.assertEqual(detail.fdc_id, 1)
        self.assertEqual(detail.nutrients.calories, 130)
        self.assertEqual(detail.nutrients.carbs_g, 28)
        self.assertEqual(detail.data_type, "SR Legacy")

    def test_get_food_unknown_id_404(self):
        with self.assertRaises(HTTPException) as ctx:
            foods.get_food(999999)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_missing_db_returns_503(self):
        with patch.object(ls, "DB_PATH", os.path.join(tempfile.gettempdir(), "nope_foods.db")):
            with self.assertRaises(HTTPException) as ctx:
                foods.search_foods(q="rice", data_type=None, require_all=True, limit=10)
            self.assertEqual(ctx.exception.status_code, 503)
            with self.assertRaises(HTTPException) as ctx2:
                foods.get_food(1)
            self.assertEqual(ctx2.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
