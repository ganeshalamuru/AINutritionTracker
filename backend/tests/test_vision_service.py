"""Unit tests for the vision/decomposition stage parsing (services/vision_service.py).

The model now returns an ingredient list (not nutrient numbers); these tests cover
the compact-JSON parsing and its tolerance of malformed output. No network.

Run from the backend/ directory:
    python -m unittest tests.test_vision_service
"""
import unittest

import services.vision_service as gs


class ParseCompactTest(unittest.TestCase):
    def test_parses_ingredient_list(self):
        raw = ('{"n":"Palak Paneer","t":"dinner","c":"high",'
               '"i":[{"f":"spinach, cooked","g":120},{"f":"paneer","g":80}]}')
        out = gs._parse_compact(raw)
        self.assertEqual(out["meal_name"], "Palak Paneer")
        self.assertEqual(out["meal_type"], "dinner")
        self.assertEqual(out["confidence"], "high")
        self.assertEqual(out["items"], [
            {"food": "spinach, cooked", "grams": 120},
            {"food": "paneer", "grams": 80},
        ])

    def test_strips_markdown_fences(self):
        raw = '```json\n{"n":"Toast","t":"breakfast","c":"low","i":[{"f":"bread","g":40}]}\n```'
        out = gs._parse_compact(raw)
        self.assertEqual(out["meal_name"], "Toast")
        self.assertEqual(out["items"], [{"food": "bread", "grams": 40}])

    def test_drops_junk_and_blank_entries(self):
        raw = ('{"n":"x","t":"snack","c":"medium",'
               '"i":[{"f":"rice","g":100},{"junk":1},{"f":"","g":5},"nope",'
               '{"f":"oil"}]}')  # last: missing grams -> defaults to 0
        out = gs._parse_compact(raw)
        self.assertEqual(out["items"], [
            {"food": "rice", "grams": 100},
            {"food": "oil", "grams": 0},
        ])

    def test_defaults_when_fields_missing(self):
        out = gs._parse_compact('{}')
        self.assertEqual(out["meal_name"], "Unknown meal")
        self.assertEqual(out["meal_type"], "snack")
        self.assertEqual(out["confidence"], "medium")
        self.assertEqual(out["items"], [])

    def test_bad_items_type_yields_empty_list(self):
        out = gs._parse_compact('{"n":"x","i":"not a list"}')
        self.assertEqual(out["items"], [])


class MockResponseTest(unittest.TestCase):
    def test_mock_response_is_item_based(self):
        self.assertIn("items", gs.MOCK_RESPONSE)
        self.assertTrue(all("food" in it and "grams" in it for it in gs.MOCK_RESPONSE["items"]))


if __name__ == "__main__":
    unittest.main()
