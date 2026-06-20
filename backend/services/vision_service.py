"""Vision / perception stage (Stage 1 of the two-stage nutrition pipeline).

Despite the historical names floating around the project, this module is provider-
agnostic: it dispatches a meal photo to whichever vision model is configured (Groq,
Gemini, or local Ollama) and returns ONLY a decomposed ingredient list — it does
NOT estimate nutrients (the model hallucinated those). The real per-100g numbers come
from the USDA lookup in usda_service.py.
"""

import base64
import json
import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod

from google import genai
from google.genai import types

from core.config import DEFAULT_MODEL, DEFAULT_PROVIDER
from core.logging_config import configure_logging

# Logger for all model traffic. Shares the app's timestamped formatter (configured
# here too so logs still show when this module is imported standalone, e.g. tests).
configure_logging()
logger = logging.getLogger("nutriai.vision")

# --- vision providers (strategy objects) ---
#
# Each provider is a VisionProvider subclass (defined below, after the shared parse helpers)
# that owns BOTH halves of a request — obtaining a ready-to-call client for the configured key
# (open/close + any build-once pool) and calling the model (analyze). They're registered by name
# in PROVIDERS; the orchestrator (analyze_meal_image) resolves ONE object and uses it for both
# halves, so client wiring and the model call can never disagree on provider.
#
# Every provider keys per request — no key is ever baked onto a process-global client. The two
# key-independent clients that DO carry an HTTP connection pool (Groq, Ollama) are built ONCE per
# process by init_clients() and reused across every /analyze; Gemini is built fresh per request.
# Following FastAPI's shared-resource pattern, each pooled provider holds its pool as an instance
# attribute, behind a module lock that serializes the one-time build:
#
#   init_clients()       — iterates PROVIDERS calling .init() to build the build-once pools (the
#                          Groq httpx pool + the keyless Ollama client). Idempotent. (core.lifespan.)
#   provider.open(key)   — per request: the ready-to-call client (Groq key injected, Gemini
#                          constructed, Ollama pooled). provider.close(client) releases it.
#
# How each provider keys, all per request, so config stays the single source of truth:
#   - Groq:   the SDK reads an `Authorization: Bearer` header per call, so open() injects the key
#             with `self._pool.with_options(api_key=...)` — a lightweight copy that reuses the
#             pooled httpx client (the key never lands on the shared pool).
#   - Gemini: google-genai keys at the client object (no genai.configure global state), so open()
#             builds a fresh genai.Client(api_key=...) per request and close() shuts it down.
#             (This is why there's no _build_gemini / cached model / reload step.)
#   - Ollama: keyless local daemon.
#
# The request hot path reads the build-once pools lock-free (an attribute read is atomic under the
# GIL); only the rare first build takes the lock.
_lock = threading.Lock()


def _build_groq():
    """One pooled Groq client for the process. The key is NOT baked in — each /analyze injects
    the configured key with `client.with_options(api_key=...)` (a copy that reuses this client's
    httpx pool), so the pool is built once and the key stays in config (its single source of
    truth). The SDK only rejects a None key, so the empty-string placeholder constructs fine."""
    from groq import Groq  # lazy: keep the module importable without the SDK installed

    return Groq(api_key="")  # placeholder; real key injected per request via with_options


def _build_ollama():
    from ollama import Client  # lazy: mirror the other builders

    # Pooled httpx client to the local daemon; no API key. The long timeout covers the
    # one-time cold model load into VRAM on the first /analyze after startup.
    return Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)


# Per-call timeout (seconds) and retry budget. The app used to hang forever when
# the model never responded — cap each call and retry at most once.
CALL_TIMEOUT = 15
MAX_RETRIES = 1  # one extra attempt after the first failure

# Local Ollama needs its own, much longer budget: the first /analyze after startup
# pays a one-time model load into VRAM, and a local vision model is slower than a
# cloud API. The 15s cloud budget would time out on the cold call. Host is overridable
# for a remote/containerized Ollama; default is the daemon's standard local port.
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_TIMEOUT = 120

# Context window for the local model. Ollama sizes its KV-cache + compute-buffer VRAM
# reservation off num_ctx and defaults to a small window (~4096), which is already enough
# for our request (one image + a short prompt + <=512 output tokens) — the 8B has produced
# correct full output at 4096. We pin it explicitly for deterministic behavior across
# Ollama versions. Do NOT raise it to "fit more context": a larger window only enlarges
# the KV reservation and pushes more model layers onto the CPU (slower) on a small GPU.
# Override via env only if a very high-res photo ever truncates.
OLLAMA_NUM_CTX = int(os.environ.get("OLLAMA_NUM_CTX", "4096"))

# Mock vision output: the dish list (macros/micros come from the lookup stage, which
# short-circuits to canned values under MOCK_GEMINI — see usda_service).
MOCK_RESPONSE = {
    "meal_name": "Grilled Chicken with Rice and Vegetables",
    "meal_type": "lunch",
    "confidence": "high",
    "dishes": [
        {
            "name": "grilled chicken",
            "grams": 150,
            "items": [{"food": "grilled chicken breast", "grams": 150}],
        },
        {
            "name": "white rice",
            "grams": 180,
            "items": [{"food": "white rice, cooked", "grams": 180}],
        },
        {
            "name": "mixed vegetables",
            "grams": 120,
            "items": [{"food": "mixed vegetables, cooked", "grams": 120}],
        },
    ],
}

NUTRITION_PROMPT = """Identify the dishes in this meal photo and estimate their weights.

Assumptions:
- If tableware size is ambiguous, assume a standard 10-inch dinner plate or 150ml bowls.
- Be conservative with weight estimates (lean low if unsure).

Output a single, compact JSON object matching this schema exactly. Do not include markdown code blocks, prose, or explanations:

{"meal_name":"Name","type":"breakfast|lunch|dinner|snack","confidence":"high|medium|low","dishes":[{"name":"dish name","total_grams":0,"components":[{"item":"ingredient/component","usda_name":"generic name","grams":0}]}]}

Guidelines:
1. One entry per distinct food item (never merge separate items).
2. "components" should break down the dish into its 2-4 primary macro-ingredients (e.g., for "Chicken Rice": chicken and rice). Avoid listing minor spices or oils unless they contribute significantly to the weight.
3. Only list components you can actually see in the photo. Do not guess ingredients that are not visible.
4. For each component also give "usda_name": a simple, generic, singular English food name a nutrition database (USDA) would list — no brand or regional terms, no fancy adjectives; include a basic cooked/raw state when it matters. Examples: jeera rice -> cooked white rice; bhindi -> okra; dahi -> plain yogurt; paneer -> paneer cheese. If "item" is already a generic English name, repeat it.
5. Ensure the sum of component grams logically matches the total_grams."""


def _is_quota_error(err: str) -> bool:
    """Daily-quota exhaustion — not worth retrying (won't recover within the call)."""
    err = err.lower()
    return (
        "quota" in err
        or "daily" in err
        or "resource_exhausted" in err
        or "per_day" in err
        or "requests_per_day" in err
    )


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _parse_items(arr) -> list[dict]:
    """Keep well-formed {item, usda_name, grams} components from the model's ingredient
    list, remapped to our internal {food, grams, usda_name} shape. `food` is the visible
    label (for display + status); `usda_name` is the generic query Stage 2 searches USDA
    with, defaulting to `food` when the model omits or blanks it (so behavior matches the
    pre-usda_name pipeline). Tolerant of junk: non-dict entries, missing/blank names, or
    bad weights are dropped; a non-numeric weight defaults to 0 (contributes nothing)."""
    out = []
    if not isinstance(arr, list):
        return out
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        food = (entry.get("item") or "").strip()
        if not food:
            continue
        usda_name = (entry.get("usda_name") or "").strip() or food
        grams = entry.get("grams")
        out.append(
            {"food": food, "grams": grams if _is_number(grams) else 0, "usda_name": usda_name}
        )
    return out


def _parse_dishes(arr) -> list[dict]:
    """Keep well-formed dishes from the model's `dishes` list, remapped to our internal
    {name, grams, items} shape: a named dish, its estimated portion grams (from the
    model's `total_grams`), and its component breakdown (from `components`, parsed by
    _parse_items, used as a lookup fallback). Tolerant of junk: non-dict entries and
    nameless dishes are dropped; a bad grams value defaults to 0."""
    out = []
    if not isinstance(arr, list):
        return out
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("name") or "").strip()
        if not name:
            continue
        grams = entry.get("total_grams")
        out.append(
            {
                "name": name,
                "grams": grams if _is_number(grams) else 0,
                "items": _parse_items(entry.get("components")),
            }
        )
    return out


# The model is free text, so coerce its meal_type/confidence to the known vocabularies
# (matching schemas.MealType / schemas.Confidence) here, before they reach the strict
# AnalyzeResponse — an off-list value can never then fail response validation.
_MEAL_TYPES = {"breakfast", "lunch", "dinner", "snack"}
_CONFIDENCE_LEVELS = {"low", "medium", "high"}


def _norm(value, allowed: set, default: str) -> str:
    v = (value or "").strip().lower()
    return v if v in allowed else default


def _parse_compact(text: str) -> dict:
    """Strip fences, parse the model's JSON, and remap to our internal named schema. The
    vision stage returns a list of dishes (each with a fallback component breakdown),
    not nutrient numbers. The model's `type` key maps to our `meal_type`."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return {
        "meal_name": data.get("meal_name") or "Unknown meal",
        "meal_type": _norm(data.get("type"), _MEAL_TYPES, "snack"),
        "confidence": _norm(data.get("confidence"), _CONFIDENCE_LEVELS, "medium"),
        "dishes": _parse_dishes(data.get("dishes")),
    }


# A vision provider owns BOTH halves of a request: obtaining a ready-to-call client for a key
# (open/close + any build-once pool) and calling the model (analyze). The orchestrator resolves
# ONE object from PROVIDERS and uses it for both, so wiring and the call can never disagree on
# provider. analyze() returns (parsed_result, raw_response_text) so the caller can log the model's
# raw output uniformly; it never constructs or closes the client (open/close own its lifecycle).
class VisionProvider(ABC):
    def init(self) -> bool:
        """Build the process-lifetime pool, if any. Idempotent; called under the module _lock by
        init_clients. Returns True if it built something (for startup logging). Default: no pool
        (e.g. Gemini, which is built fresh per request in open())."""
        return False

    @abstractmethod
    def open(self, api_key: str):
        """Return a ready-to-call client for THIS request (key injected/constructed). The key is
        guaranteed non-empty for keyed providers (config.get_api_key in meal_service raises 503
        first). Raises if init_clients never ran for a pooled provider."""

    def close(self, client) -> None:  # noqa: B027 — intentional no-op default; only Gemini overrides
        """Release a per-request client. Default no-op: the pooled clients outlive the request
        (closing Groq's with_options copy would tear down the shared httpx pool)."""

    @abstractmethod
    def analyze(self, client, image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
        """Call the model and return (parsed_result, raw_response_text)."""


class GeminiProvider(VisionProvider):
    """google-genai keys at the client object (no genai.configure global state), so each request
    builds a fresh genai.Client(api_key=...) and close() shuts it down — no pool, no reload step."""

    def open(self, api_key: str):
        return genai.Client(api_key=api_key)

    def close(self, client) -> None:
        client.close()

    def analyze(self, client, image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
        response = client.models.generate_content(
            model=model,
            contents=[prompt, types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")],
            config=types.GenerateContentConfig(
                max_output_tokens=1024,
                temperature=0,
                # google-genai's HttpOptions.timeout is in MILLISECONDS (the field's own docstring
                # says so), unlike our seconds-based CALL_TIMEOUT — hence the * 1000.
                http_options=types.HttpOptions(timeout=CALL_TIMEOUT * 1000),
            ),
        )
        raw = response.text
        return _parse_compact(raw), raw


class GroqProvider(VisionProvider):
    """One pooled httpx client built once; the key is injected per request via with_options (a
    copy that reuses the pool), so the key stays in config and never lands on the shared pool."""

    _pool = None  # pooled groq.Groq, built once by init(); key injected per request

    def init(self) -> bool:
        if self._pool is None:
            self._pool = _build_groq()
            return True
        return False

    def open(self, api_key: str):
        if self._pool is None:
            raise RuntimeError("Groq client not initialized.")
        return self._pool.with_options(api_key=api_key)

    def analyze(self, client, image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
        b64 = base64.b64encode(image_bytes).decode()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                        },
                    ],
                }
            ],
            temperature=0,
            max_tokens=1024,
            response_format={"type": "json_object"},
            timeout=CALL_TIMEOUT,
        )
        raw = response.choices[0].message.content or ""
        return _parse_compact(raw), raw


class OllamaProvider(VisionProvider):
    """Local vision via the official Ollama client (no API key); one pooled client to the local
    daemon, built once and reused (open() ignores the key)."""

    _pool = None  # official ollama.Client (local daemon, no key), built once by init()

    def init(self) -> bool:
        if self._pool is None:
            self._pool = _build_ollama()
            return True
        return False

    def open(self, api_key: str):
        if self._pool is None:
            raise RuntimeError("Ollama client not initialized.")
        return self._pool

    def analyze(self, client, image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
        """Mirrors GroqProvider.analyze: the image is passed as raw bytes (the client base64-encodes
        it), `format="json"` is plain JSON mode like Groq's response_format — the current qwen3-vl
        models keep our {meal_name,type,confidence,dishes:[...]} shape from the prompt alone (verified
        on the 4B and 8B), so no explicit JSON schema is needed; temperature 0 for determinism."""
        response = client.chat(
            model=model,
            messages=[{"role": "user", "content": prompt, "images": [image_bytes]}],
            format="json",
            options={"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
            stream=False,
        )
        raw = response.message.content or ""
        return _parse_compact(raw), raw


PROVIDERS = {
    "gemini": GeminiProvider(),
    "groq": GroqProvider(),
    "ollama": OllamaProvider(),
}


def init_clients():
    """Build the process-lifetime vision pools that are **built once and NEVER rebuilt**: the Groq
    httpx connection pool (the key is injected per request via with_options, never baked in) and the
    keyless Ollama client (a fixed local HTTP endpoint). Iterates PROVIDERS calling each .init(), so
    a new provider needs no change here. Idempotent — only builds what's missing, so it's a cheap
    no-op once warm. No DB access (these don't depend on config). Called at startup (core.lifespan);
    a key/model change needs no rebuild, since every provider keys per request."""
    with _lock:
        built = [name for name, provider in PROVIDERS.items() if provider.init()]
    if built:
        logger.info("vision clients initialized (built once, never rebuilt): %s", ", ".join(built))


def analyze_meal_image(
    image_bytes: bytes,
    user_note: str = "",
    model: str = DEFAULT_MODEL,
    provider: str = DEFAULT_PROVIDER,
    api_key: str = "",
) -> dict:
    if os.environ.get("MOCK_GEMINI", "").lower() in ("1", "true"):
        logger.info("request -> provider=mock model=mock (returning canned response)")
        return MOCK_RESPONSE

    prompt = NUTRITION_PROMPT
    if user_note and user_note.strip():
        prompt += f"\n\nAdditional context from the user: {user_note.strip()}"

    provider = provider or DEFAULT_PROVIDER
    impl = PROVIDERS.get(provider) or PROVIDERS[DEFAULT_PROVIDER]
    # Normalize so the log line names the provider we actually run (an unknown provider falls back
    # to DEFAULT_PROVIDER for BOTH the client and the call — they can't disagree now).
    provider = provider if provider in PROVIDERS else DEFAULT_PROVIDER
    # Resolve the ready-to-call client once (Gemini's is built per request here and reused across
    # retries); impl.close() releases it afterwards — a no-op for the pooled Groq/Ollama clients,
    # client.close() for the per-request Gemini one.
    client = impl.open(api_key)

    logger.info(
        "request -> provider=%s model=%s | image=%dB | note=%r",
        provider,
        model,
        len(image_bytes),
        (user_note or "")[:120],
    )

    last_err = None
    try:
        for attempt in range(MAX_RETRIES + 1):
            start = time.monotonic()
            try:
                result, raw = impl.analyze(client, image_bytes, prompt, model)
                elapsed = time.monotonic() - start
                logger.info(
                    "response <- provider=%s model=%s | %.2fs | raw=%s",
                    provider,
                    model,
                    elapsed,
                    # Flatten any pretty-printed/multi-line model JSON onto one physical line so
                    # the whole response stays on a single prefixed log record. Without this, only
                    # the first line carries the timestamp/req prefix and line-oriented log tooling
                    # silently drops the bare continuation lines (looks like missing ingredients).
                    " ".join((raw or "").split()),
                )
                return result
            except Exception as e:
                elapsed = time.monotonic() - start
                last_err = e
                # Daily quota won't recover within this request — fail fast.
                if _is_quota_error(str(e)):
                    logger.error(
                        "error <- provider=%s model=%s | %.2fs | quota: %s: %s",
                        provider,
                        model,
                        elapsed,
                        type(e).__name__,
                        e,
                    )
                    raise
                # Timeout / per-minute rate / transient — retry once with a short backoff.
                if attempt < MAX_RETRIES:
                    logger.warning(
                        "retry %d/%d <- provider=%s model=%s | %.2fs | %s: %s",
                        attempt + 1,
                        MAX_RETRIES,
                        provider,
                        model,
                        elapsed,
                        type(e).__name__,
                        e,
                    )
                    time.sleep(1.5)
                    continue
                logger.error(
                    "error <- provider=%s model=%s | %.2fs | %s: %s",
                    provider,
                    model,
                    elapsed,
                    type(e).__name__,
                    e,
                )
                raise last_err from None
    finally:
        impl.close(client)
