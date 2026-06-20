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
    Ollama client), each owned by its provider, and is idempotent. Offline: constructing the
    Groq client makes no network call, and _build_ollama is stubbed so the test stays hermetic."""

    def tearDown(self):
        gs.PROVIDERS["groq"]._pool = None
        gs.PROVIDERS["ollama"]._pool = None

    def test_builds_both_pools_once_and_is_idempotent(self):
        with patch.object(gs, "_build_ollama", return_value=object()) as build_ollama:
            gs.init_clients()
            groq = gs.PROVIDERS["groq"]._pool
            ollama = gs.PROVIDERS["ollama"]._pool
            self.assertIsNotNone(groq)
            self.assertIsNotNone(ollama)
            # A second call must not rebuild — same objects, _build_ollama not called again.
            gs.init_clients()
            self.assertIs(gs.PROVIDERS["groq"]._pool, groq)
            self.assertIs(gs.PROVIDERS["ollama"]._pool, ollama)
            build_ollama.assert_called_once()


class ProviderOpenCloseTest(unittest.TestCase):
    """Each provider owns both halves: open() resolves the ready-to-call client for a request and
    close() releases it. Groq returns the build-once pool with the key injected via with_options (a
    copy reusing the pool) + a no-op close; Ollama returns the pooled client + a no-op close; Gemini
    builds a fresh keyed genai.Client per request and close() shuts it down. Offline: genai.Client
    is patched."""

    def tearDown(self):
        gs.PROVIDERS["groq"]._pool = None
        gs.PROVIDERS["ollama"]._pool = None

    def test_groq_open_injects_key_and_close_is_no_op(self):
        sentinel = object()

        class FakeGroq:
            def with_options(self, **kwargs):
                self.with_options_kwargs = kwargs
                return sentinel

        pool = FakeGroq()
        gs.PROVIDERS["groq"]._pool = pool
        client = gs.PROVIDERS["groq"].open("secret-key")
        self.assertIs(client, sentinel)  # the key-injected copy, not the shared pool
        # open() also hands the SDK the retry budget so Groq retries internally (the app loop
        # is then a no-op for Groq — app_retries == 0).
        self.assertEqual(
            pool.with_options_kwargs, {"api_key": "secret-key", "max_retries": gs.MAX_RETRIES}
        )
        # close must NOT tear down the shared pool — the base no-op leaves it intact.
        gs.PROVIDERS["groq"].close(client)
        self.assertIs(gs.PROVIDERS["groq"]._pool, pool)

    def test_groq_open_raises_when_pool_not_built(self):
        gs.PROVIDERS["groq"]._pool = None
        with self.assertRaises(RuntimeError):
            gs.PROVIDERS["groq"].open("key")

    def test_ollama_open_returns_pool(self):
        pool = object()
        gs.PROVIDERS["ollama"]._pool = pool
        self.assertIs(gs.PROVIDERS["ollama"].open(""), pool)

    def test_ollama_open_raises_when_pool_not_built(self):
        gs.PROVIDERS["ollama"]._pool = None
        with self.assertRaises(RuntimeError):
            gs.PROVIDERS["ollama"].open("")

    def test_gemini_open_builds_per_request_client_and_close_shuts_it_down(self):
        closed = []
        fake = type("FakeGenaiClient", (), {"close": lambda self: closed.append(True)})()
        with patch.object(gs.genai, "Client", return_value=fake) as ctor:
            client = gs.PROVIDERS["gemini"].open("g-key")
            gs.PROVIDERS["gemini"].close(client)
        ctor.assert_called_once_with(api_key="g-key")  # object-scoped key, per request
        self.assertIs(client, fake)
        self.assertEqual(closed, [True])  # close shuts down the per-request httpx connection


class AppRetriesTest(unittest.TestCase):
    """The orchestrator's app-level retry budget is per provider: Groq/Gemini delegate retries to
    their SDK (so they must NOT also loop here, else attempts multiply), while Ollama's SDK has no
    retry and keeps one app-level attempt."""

    def test_sdk_backed_providers_dont_app_retry_but_ollama_does(self):
        self.assertEqual(gs.PROVIDERS["groq"].app_retries, 0)
        self.assertEqual(gs.PROVIDERS["gemini"].app_retries, 0)
        self.assertEqual(gs.PROVIDERS["ollama"].app_retries, gs.MAX_RETRIES)


class GroqAnalyzeTest(unittest.TestCase):
    """GroqProvider.analyze takes the ready-to-call client (key already injected by open()) and
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
        result, raw = gs.PROVIDERS["groq"].analyze(client, b"\xff\xd8img", "PROMPT", "scout-model")
        self.assertEqual(self.create_kwargs["model"], "scout-model")
        self.assertEqual(raw, content)
        self.assertEqual(result["meal_name"], "Lunch")


class GeminiAnalyzeTest(unittest.TestCase):
    """GeminiProvider.analyze takes the per-request keyed genai.Client (built by open()) and parses
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
        result, raw = gs.PROVIDERS["gemini"].analyze(client, b"\xff\xd8img", "PROMPT", "gemini-x")

        self.assertEqual(raw, content)
        self.assertEqual(self.gen_kwargs["model"], "gemini-x")
        # contents = [prompt, image part]; the prompt is forwarded verbatim.
        self.assertEqual(self.gen_kwargs["contents"][0], "PROMPT")
        # Per-request timeout is set in milliseconds (CALL_TIMEOUT seconds * 1000).
        self.assertEqual(self.gen_kwargs["config"].http_options.timeout, gs.CALL_TIMEOUT * 1000)
        # The SDK owns the retry: attempts counts the first call, so MAX_RETRIES + 1 attempts.
        self.assertEqual(
            self.gen_kwargs["config"].http_options.retry_options.attempts, gs.MAX_RETRIES + 1
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
    """OllamaProvider.analyze takes the pooled client (returned by open()) and parses
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
        result, raw = gs.PROVIDERS["ollama"].analyze(
            client, b"\xff\xd8jpegbytes", "PROMPT", "qwen3-vl:8b-instruct"
        )

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


class UnknownProviderFallbackTest(unittest.TestCase):
    """An unknown provider must resolve to DEFAULT_PROVIDER for BOTH the client and the call, so
    open() and analyze() can never come from different providers (the pre-refactor bug, where the
    client fell through to groq while the analyze fn fell through to gemini)."""

    def test_unknown_provider_routes_entirely_through_default(self):
        default = gs.PROVIDERS[gs.DEFAULT_PROVIDER]
        sentinel_client = object()
        parsed = {"meal_name": "x", "meal_type": "snack", "confidence": "medium", "dishes": []}
        with (
            patch.dict(gs.os.environ, {"MOCK_GEMINI": ""}),
            patch.object(default, "open", return_value=sentinel_client) as open_,
            patch.object(default, "analyze", return_value=(parsed, "{}")) as analyze_,
            patch.object(default, "close") as close_,
        ):
            out = gs.analyze_meal_image(b"\xff\xd8img", provider="bogus", api_key="k")
        open_.assert_called_once_with("k")
        # analyze got the SAME client open() produced — no cross-provider mismatch.
        self.assertIs(analyze_.call_args.args[0], sentinel_client)
        close_.assert_called_once_with(sentinel_client)
        self.assertEqual(out, parsed)


if __name__ == "__main__":
    unittest.main()
