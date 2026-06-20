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


class ClientForTest(unittest.TestCase):
    """_client_for resolves the ready-to-call client for a request plus a cleanup hook. Groq
    returns the build-once pool with the key injected via with_options (a copy reusing the pool)
    + a no-op cleanup; Ollama returns the pooled client + a no-op cleanup; Gemini builds a fresh
    keyed genai.Client per request + its close as cleanup. Offline: genai.Client is patched."""

    def tearDown(self):
        gs._groq_client = None
        gs._ollama_client = None

    def test_groq_injects_key_and_no_op_cleanup(self):
        sentinel = object()

        class FakeGroq:
            def with_options(self, **kwargs):
                self.with_options_kwargs = kwargs
                return sentinel

        gs._groq_client = FakeGroq()
        client, close = gs._client_for("groq", "secret-key")
        self.assertIs(client, sentinel)  # the key-injected copy, not the shared pool
        self.assertEqual(gs._groq_client.with_options_kwargs, {"api_key": "secret-key"})
        self.assertIs(close, gs._noop)  # never close the shared pool

    def test_groq_raises_when_pool_not_built(self):
        gs._groq_client = None
        with self.assertRaises(RuntimeError):
            gs._client_for("groq", "key")

    def test_ollama_returns_pool_and_no_op_cleanup(self):
        gs._ollama_client = object()
        client, close = gs._client_for("ollama", "")
        self.assertIs(client, gs._ollama_client)
        self.assertIs(close, gs._noop)

    def test_ollama_raises_when_pool_not_built(self):
        gs._ollama_client = None
        with self.assertRaises(RuntimeError):
            gs._client_for("ollama", "")

    def test_gemini_builds_per_request_client_and_returns_close(self):
        fake = type("FakeGenaiClient", (), {"close": lambda self: None})()
        with patch.object(gs.genai, "Client", return_value=fake) as ctor:
            client, close = gs._client_for("gemini", "g-key")
        ctor.assert_called_once_with(api_key="g-key")  # object-scoped key, per request
        self.assertIs(client, fake)
        self.assertEqual(close, fake.close)  # cleanup closes the per-request httpx connection


class GroqAnalyzeTest(unittest.TestCase):
    """_groq_analyze takes the ready-to-call client (key already injected by _client_for) and
    parses the chat completion. No network: the client is a fake that records its call."""

    def test_calls_completions_and_parses(self):
        content = '{"meal_name":"Lunch","type":"lunch","confidence":"high","dishes":[]}'
        test = self

        class Completions:
            def create(self, **kwargs):
                test.create_kwargs = kwargs
                msg = type("M", (), {"content": content})
                choice = type("C", (), {"message": msg})
                return type("R", (), {"choices": [choice]})

        client = type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})})()
        result, raw = gs._groq_analyze(client, b"\xff\xd8img", "PROMPT", "scout-model")
        self.assertEqual(self.create_kwargs["model"], "scout-model")
        self.assertEqual(raw, content)
        self.assertEqual(result["meal_name"], "Lunch")


class GeminiAnalyzeTest(unittest.TestCase):
    """_gemini_analyze takes the per-request keyed genai.Client (built by _client_for) and parses
    response.text. No network: the client is a fake recording its generate_content call."""

    def test_calls_generate_content_and_parses(self):
        content = (
            '{"meal_name":"Lunch","type":"lunch","confidence":"high","dishes":['
            '{"name":"dosa","total_grams":120,"components":[{"item":"rice","grams":80}]}]}'
        )
        test = self

        class Models:
            def generate_content(self, **kwargs):
                test.gen_kwargs = kwargs
                return type("R", (), {"text": content})

        client = type("Client", (), {"models": Models()})()
        result, raw = gs._gemini_analyze(client, b"\xff\xd8img", "PROMPT", "gemini-x")

        self.assertEqual(raw, content)
        self.assertEqual(self.gen_kwargs["model"], "gemini-x")
        # contents = [prompt, image part]; the prompt is forwarded verbatim.
        self.assertEqual(self.gen_kwargs["contents"][0], "PROMPT")
        # Per-request timeout is set in milliseconds (CALL_TIMEOUT seconds * 1000).
        self.assertEqual(
            self.gen_kwargs["config"].http_options.timeout, gs.CALL_TIMEOUT * 1000
        )
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


class OllamaAnalyzeTest(unittest.TestCase):
    """_ollama_analyze takes the pooled client (passed in by _client_for) and parses
    message.content via _parse_compact. No network: the client is a fake."""

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

        client = FakeClient()
        result, raw = gs._ollama_analyze(client, b"\xff\xd8jpegbytes", "PROMPT", "qwen3-vl:8b-instruct")

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
        kwargs = client.calls[0]
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
