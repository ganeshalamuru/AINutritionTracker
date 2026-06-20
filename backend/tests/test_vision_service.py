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
                    "items": [
                        {"food": "rice", "grams": 90, "usda_name": "rice"},
                        {"food": "urad dal", "grams": 30, "usda_name": "urad dal"},
                    ],
                },
                {
                    "name": "sambar",
                    "grams": 150,
                    "items": [{"food": "toor dal", "grams": 30, "usda_name": "toor dal"}],
                },
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
                {
                    "name": "toast",
                    "grams": 40,
                    "items": [{"food": "bread", "grams": 40, "usda_name": "bread"}],
                },
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
                    "items": [
                        {"food": "rice", "grams": 100, "usda_name": "rice"},
                        {"food": "oil", "grams": 0, "usda_name": "oil"},
                    ],
                },
            ],
        )

    def test_usda_name_captured_and_defaults_to_item(self):
        raw = (
            '{"meal_name":"x","type":"lunch","confidence":"high","dishes":[{"name":"thali",'
            '"total_grams":200,"components":['
            '{"item":"jeera rice","usda_name":"cooked white rice","grams":120},'  # generic name kept
            '{"item":"bhindi","usda_name":"  ","grams":50},'  # blank usda_name -> falls back to item
            '{"item":"dahi","grams":30}]}]}'  # missing usda_name -> falls back to item
        )
        out = gs._parse_compact(raw)
        self.assertEqual(
            out["dishes"][0]["items"],
            [
                {"food": "jeera rice", "grams": 120, "usda_name": "cooked white rice"},
                {"food": "bhindi", "grams": 50, "usda_name": "bhindi"},
                {"food": "dahi", "grams": 30, "usda_name": "dahi"},
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


class InitClientsTest(unittest.TestCase):
    """init_clients builds the build-once / never-rebuilt pools (Groq httpx pool + keyless
    Ollama client) and is idempotent. Offline: constructing the Groq client makes no network
    call, and _build_ollama is stubbed so the test stays hermetic."""

    def tearDown(self):
        gs._groq_client = None
        gs._ollama_client = None

    def test_builds_both_pools_once_and_is_idempotent(self):
        with patch.object(gs, "_build_ollama", return_value=object()) as build_ollama:
            gs.init_clients()
            groq, ollama = gs._groq_client, gs._ollama_client
            self.assertIsNotNone(groq)
            self.assertIsNotNone(ollama)
            # A second call must not rebuild — same objects, _build_ollama not called again.
            gs.init_clients()
            self.assertIs(gs._groq_client, groq)
            self.assertIs(gs._ollama_client, ollama)
            build_ollama.assert_called_once()


class ReloadClientsTest(unittest.TestCase):
    """reload_clients rebuilds ONLY the Gemini model on a config change; the build-once
    Groq/Ollama pools (init_clients) are reused, never rebuilt, and the Groq key is NOT cached
    here (it's injected per request in _groq_analyze). Offline: constructing Groq makes no
    network call, _build_gemini/_build_ollama are stubbed, and config access is stubbed."""

    def setUp(self):
        self.gemini_builds = 0

    def _fake_build_gemini(self, api_key, model):
        self.gemini_builds += 1
        return ("gemini", api_key, model)

    def _reload(self, gemini_key=""):
        values = {"groq_api_key": "ignored-here", "gemini_api_key": gemini_key}
        with (
            patch.object(gs.config, "get_vision_config", return_value=("groq", "some-model")),
            patch.object(
                gs.config,
                "get_value",
                side_effect=lambda db, key, default="": values.get(key, default),
            ),
            patch.object(gs, "_build_ollama", return_value=object()),
            patch.object(gs, "_build_gemini", side_effect=self._fake_build_gemini),
        ):
            gs.reload_clients(db=None)

    def tearDown(self):
        gs._groq_client = None
        gs._gemini_model = None
        gs._ollama_client = None

    def test_pools_built_once_and_reused_not_rebuilt(self):
        self._reload()
        groq, ollama = gs._groq_client, gs._ollama_client
        self.assertIsNotNone(groq)
        self.assertIsNotNone(ollama)
        # The Groq key is never cached on the shared client — left empty; injected per request.
        self.assertEqual(groq.api_key, "")
        # A second reload must NOT rebuild the pools — same object identity proves it.
        self._reload()
        self.assertIs(gs._groq_client, groq)
        self.assertIs(gs._ollama_client, ollama)

    def test_gemini_rebuilt_every_reload(self):
        self._reload(gemini_key="g1")
        self.assertEqual(gs._gemini_model, ("gemini", "g1", "some-model"))
        self._reload(gemini_key="g2")
        self.assertEqual(gs._gemini_model, ("gemini", "g2", "some-model"))
        self.assertEqual(self.gemini_builds, 2)  # torn down + rebuilt each time

    def test_no_gemini_when_key_blank(self):
        self._reload(gemini_key="")
        self.assertIsNone(gs._gemini_model)
        self.assertEqual(self.gemini_builds, 0)


class GroqAnalyzeTest(unittest.TestCase):
    """_groq_analyze injects the per-request key via with_options (a copy that reuses the
    pooled client) rather than reading a cached key, and guards on the supplied key. No
    network: the client is a fake that records what it was called with."""

    def tearDown(self):
        gs._groq_client = None

    def _fake_client(self, content):
        test = self

        class Completions:
            def create(self, **kwargs):
                test.create_kwargs = kwargs
                msg = type("M", (), {"content": content})
                choice = type("C", (), {"message": msg})
                return type("R", (), {"choices": [choice]})

        class Scoped:
            chat = type("Chat", (), {"completions": Completions()})

        class Client:
            def with_options(self, **kwargs):
                test.with_options_kwargs = kwargs
                return Scoped()

        return Client()

    def test_injects_key_per_request_via_with_options(self):
        content = '{"meal_name":"Lunch","type":"lunch","confidence":"high","dishes":[]}'
        gs._groq_client = self._fake_client(content)
        result, raw = gs._groq_analyze(b"\xff\xd8img", "PROMPT", "scout-model", "secret-key")
        # The configured key is passed per request, not pulled from a cached client attribute.
        self.assertEqual(self.with_options_kwargs, {"api_key": "secret-key"})
        self.assertEqual(self.create_kwargs["model"], "scout-model")
        self.assertEqual(raw, content)
        self.assertEqual(result["meal_name"], "Lunch")

    def test_raises_when_key_missing(self):
        gs._groq_client = self._fake_client("{}")
        with self.assertRaises(RuntimeError):
            gs._groq_analyze(b"img", "PROMPT", "scout-model", "")

    def test_raises_when_client_not_built(self):
        gs._groq_client = None
        with self.assertRaises(RuntimeError):
            gs._groq_analyze(b"img", "PROMPT", "scout-model", "key")


class OllamaAnalyzeTest(unittest.TestCase):
    """_ollama_analyze calls the official ollama client's chat() and parses
    message.content via _parse_compact. No network: the client is a fake."""

    def tearDown(self):
        gs._ollama_client = None

    def test_calls_client_and_parses_dish_list(self):
        content = (
            '{"meal_name":"Lunch","type":"lunch","confidence":"high","dishes":['
            '{"name":"dosa","total_grams":120,"components":[{"item":"rice","grams":80}]}]}'
        )

        class FakeResponse:
            class message:  # noqa: N801 — mirrors ollama's response.message.content
                pass

        class FakeClient:
            def __init__(self):
                self.calls = []

            def chat(self, **kwargs):
                self.calls.append(kwargs)
                resp = FakeResponse()
                resp.message.content = content
                return resp

        gs._ollama_client = FakeClient()
        # api_key is accepted for a uniform dispatch signature but ignored (Ollama is keyless).
        result, raw = gs._ollama_analyze(b"\xff\xd8jpegbytes", "PROMPT", "qwen3-vl:8b-instruct", "")

        self.assertEqual(raw, content)
        self.assertEqual(
            result["dishes"],
            [
                {
                    "name": "dosa",
                    "grams": 120,
                    "items": [{"food": "rice", "grams": 80, "usda_name": "rice"}],
                }
            ],
        )
        # Called with the model, plain JSON mode (like Groq — no explicit schema), the raw
        # image bytes (the client base64-encodes them), and the capped num_ctx.
        kwargs = gs._ollama_client.calls[0]
        self.assertEqual(kwargs["model"], "qwen3-vl:8b-instruct")
        self.assertEqual(kwargs["format"], "json")
        self.assertFalse(kwargs["stream"])
        # num_ctx is capped so Ollama doesn't reserve VRAM for the model's 262k context
        # and offload layers to CPU.
        self.assertEqual(kwargs["options"]["num_ctx"], gs.OLLAMA_NUM_CTX)
        self.assertEqual(kwargs["messages"][0]["content"], "PROMPT")
        self.assertEqual(kwargs["messages"][0]["images"], [b"\xff\xd8jpegbytes"])


class MockResponseTest(unittest.TestCase):
    def test_mock_response_is_dish_based(self):
        self.assertIn("dishes", gs.MOCK_RESPONSE)
        for d in gs.MOCK_RESPONSE["dishes"]:
            self.assertIn("name", d)
            self.assertIn("grams", d)
            self.assertTrue(all("food" in it and "grams" in it for it in d["items"]))


if __name__ == "__main__":
    unittest.main()
