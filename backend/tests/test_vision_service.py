"""Unit tests for the vision/decomposition stage parsing (services/vision_service.py).

The model returns a list of dishes (each with a fallback ingredient breakdown), not
nutrient numbers; these tests cover the compact-JSON parsing and its tolerance of
malformed output. No network.

Run from the backend/ directory:
    python -m unittest tests.test_vision_service
"""

import unittest
from unittest.mock import patch

import services.vision_service as gs


class ParseCompactTest(unittest.TestCase):
    def test_parses_dish_list(self):
        raw = (
            '{"meal_name":"South Indian Breakfast","type":"breakfast","confidence":"high","dishes":['
            '{"name":"idli","total_grams":160,"components":[{"item":"rice","grams":90},{"item":"urad dal","grams":30}]},'
            '{"name":"sambar","total_grams":150,"components":[{"item":"toor dal","grams":30}]}]}'
        )
        out = gs._parse_compact(raw)
        self.assertEqual(out["meal_name"], "South Indian Breakfast")
        self.assertEqual(out["meal_type"], "breakfast")
        self.assertEqual(out["confidence"], "high")
        self.assertEqual(
            out["dishes"],
            [
                {
                    "name": "idli",
                    "grams": 160,
                    "items": [{"food": "rice", "grams": 90}, {"food": "urad dal", "grams": 30}],
                },
                {"name": "sambar", "grams": 150, "items": [{"food": "toor dal", "grams": 30}]},
            ],
        )

    def test_strips_markdown_fences(self):
        raw = (
            '```json\n{"meal_name":"Toast","type":"breakfast","confidence":"low","dishes":['
            '{"name":"toast","total_grams":40,"components":[{"item":"bread","grams":40}]}]}\n```'
        )
        out = gs._parse_compact(raw)
        self.assertEqual(out["meal_name"], "Toast")
        self.assertEqual(
            out["dishes"],
            [
                {"name": "toast", "grams": 40, "items": [{"food": "bread", "grams": 40}]},
            ],
        )

    def test_drops_junk_dishes_and_items(self):
        raw = (
            '{"meal_name":"x","type":"snack","confidence":"medium","dishes":['
            '{"name":"rice bowl","total_grams":100,"components":[{"item":"rice","grams":100},{"junk":1},{"item":"","grams":5},"nope",{"item":"oil"}]},'
            '{"total_grams":50},"bad",{"name":"  "}]}'
        )  # nameless/blank dishes dropped; oil missing grams -> 0
        out = gs._parse_compact(raw)
        self.assertEqual(
            out["dishes"],
            [
                {
                    "name": "rice bowl",
                    "grams": 100,
                    "items": [{"food": "rice", "grams": 100}, {"food": "oil", "grams": 0}],
                },
            ],
        )

    def test_defaults_when_fields_missing(self):
        out = gs._parse_compact("{}")
        self.assertEqual(out["meal_name"], "Unknown meal")
        self.assertEqual(out["meal_type"], "snack")
        self.assertEqual(out["confidence"], "medium")
        self.assertEqual(out["dishes"], [])

    def test_bad_dishes_type_yields_empty_list(self):
        self.assertEqual(gs._parse_compact('{"meal_name":"x","dishes":"not a list"}')["dishes"], [])

    def test_bad_items_type_yields_dish_with_empty_items(self):
        out = gs._parse_compact(
            '{"meal_name":"x","dishes":[{"name":"a","total_grams":10,"components":"nope"}]}'
        )
        self.assertEqual(out["dishes"], [{"name": "a", "grams": 10, "items": []}])


class ReloadClientsTest(unittest.TestCase):
    """reload_clients builds a client only for a provider that has a key configured.
    Offline: constructing the Groq client makes no network call, and config access is
    stubbed so no DB is touched."""

    def _reload(self, groq_key, gemini_key=""):
        values = {"groq_api_key": groq_key, "gemini_api_key": gemini_key}
        with (
            patch.object(gs.config, "get_vision_config", return_value=("groq", "some-model")),
            patch.object(
                gs.config,
                "get_value",
                side_effect=lambda db, key, default="": values.get(key, default),
            ),
        ):
            gs.reload_clients(db=None)

    def tearDown(self):
        gs._groq_client = None
        gs._gemini_model = None

    def test_groq_client_built_when_key_present(self):
        self._reload(groq_key="test-key")
        self.assertIsNotNone(gs._groq_client)

    def test_no_groq_client_when_key_blank(self):
        self._reload(groq_key="")
        self.assertIsNone(gs._groq_client)


class OllamaAnalyzeTest(unittest.TestCase):
    """_ollama_analyze posts to the local Ollama daemon and parses message.content via
    _parse_compact. No network: requests.post is stubbed."""

    def test_posts_image_and_parses_dish_list(self):
        content = (
            '{"meal_name":"Lunch","type":"lunch","confidence":"high","dishes":['
            '{"name":"dosa","total_grams":120,"components":[{"item":"rice","grams":80}]}]}'
        )

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {"message": {"content": content}}

        with patch.object(gs.requests, "post", return_value=FakeResponse()) as post:
            result, raw = gs._ollama_analyze(b"\xff\xd8jpegbytes", "PROMPT", "qwen3-vl:8b-instruct")

        self.assertEqual(raw, content)
        self.assertEqual(
            result["dishes"],
            [{"name": "dosa", "grams": 120, "items": [{"food": "rice", "grams": 80}]}],
        )
        # Sent to the chat endpoint with the model, JSON format, and a base64 image.
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertTrue(url.endswith("/api/chat"))
        self.assertEqual(payload["model"], "qwen3-vl:8b-instruct")
        # format carries the response JSON schema (constrained decoding), not just "json".
        self.assertEqual(payload["format"], gs._OLLAMA_FORMAT)
        self.assertIn("dishes", payload["format"]["required"])
        self.assertFalse(payload["stream"])
        # num_ctx is capped so Ollama doesn't reserve VRAM for the model's 262k context
        # and offload layers to CPU.
        self.assertEqual(payload["options"]["num_ctx"], gs.OLLAMA_NUM_CTX)
        self.assertEqual(payload["messages"][0]["content"], "PROMPT")
        self.assertEqual(len(payload["messages"][0]["images"]), 1)


class MockResponseTest(unittest.TestCase):
    def test_mock_response_is_dish_based(self):
        self.assertIn("dishes", gs.MOCK_RESPONSE)
        for d in gs.MOCK_RESPONSE["dishes"]:
            self.assertIn("name", d)
            self.assertIn("grams", d)
            self.assertTrue(all("food" in it and "grams" in it for it in d["items"]))


if __name__ == "__main__":
    unittest.main()
