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

import google.generativeai as genai

from core import config
from core.config import DEFAULT_MODEL, DEFAULT_PROVIDER
from core.logging_config import configure_logging

# Logger for all model traffic. Shares the app's timestamped formatter (configured
# here too so logs still show when this module is imported standalone, e.g. tests).
configure_logging()
logger = logging.getLogger("nutriai.vision")

# --- shared vision clients ---
#
# A vision client carries its own HTTP connection pool, so we build it ONCE per process and
# reuse it across every /analyze. Following FastAPI's documented pattern for shared resources,
# the clients live in module globals. Lifecycle is split into two functions so it's explicit
# which clients are rebuilt and which are not:
#
#   init_clients()    — built ONCE, NEVER rebuilt: the Groq httpx pool + the keyless Ollama
#                       client. Both are key/config-independent. (core.lifespan, at startup.)
#   reload_clients(db)— applies config on a key/model change: REBUILDS only the Gemini model.
#
# Groq's key is NOT cached on the client and never appears in reload_clients: the SDK sends it
# as an `Authorization: Bearer` header it reads *per request*, so each /analyze injects the
# configured key with `client.with_options(api_key=...)` (a lightweight copy that reuses the
# pooled httpx client). Config stays the single source of truth for the key. Gemini is the
# exception that must rebuild: google-generativeai 0.8.3 has no per-request key — `genai.configure`
# mutates process-global state and resets the cached gRPC transport, so "init per call" would
# rebuild the gRPC channel every request. Object-scoped keying there needs the newer google-genai
# SDK. Ollama is keyless.
#
# The lock serializes the rare Gemini rebuild; the request hot path (_groq_analyze /
# _gemini_analyze / _ollama_analyze) just reads the global, which is atomic under the GIL —
# no per-call lock.
_lock = threading.Lock()
_groq_client = None  # pooled groq.Groq, built once; key swapped on .api_key per config change
_gemini_model = None  # built from (gemini_api_key, vision_model)
_ollama_client = None  # official ollama.Client (local daemon, no key)


def _build_groq():
    """One pooled Groq client for the process. The key is NOT baked in — each /analyze injects
    the configured key with `client.with_options(api_key=...)` (a copy that reuses this client's
    httpx pool), so the pool is built once and the key stays in config (its single source of
    truth). The SDK only rejects a None key, so the empty-string placeholder constructs fine."""
    from groq import Groq  # lazy: keep the module importable without the SDK installed

    return Groq(api_key="")  # placeholder; real key injected per request via with_options


def _build_gemini(api_key: str, model: str):
    genai.configure(api_key=api_key)  # process-global key (matches the one-key reality)
    return genai.GenerativeModel(
        model,
        generation_config={"max_output_tokens": 1024, "temperature": 0},
    )


def _build_ollama():
    from ollama import Client  # lazy: mirror the other builders

    # Pooled httpx client to the local daemon; no API key. The long timeout covers the
    # one-time cold model load into VRAM on the first /analyze after startup.
    return Client(host=OLLAMA_HOST, timeout=OLLAMA_TIMEOUT)


def init_clients():
    """Build the process-lifetime vision clients that are **built once and NEVER rebuilt**:
    the Groq httpx connection pool (the key is injected per request via with_options, never
    baked in) and the keyless Ollama client (a fixed local HTTP endpoint). Idempotent — only
    builds what's missing, so it's a cheap no-op once warm. No DB access (these don't depend
    on config). Called at startup (core.lifespan), and defensively by reload_clients so the
    config-change path can't run before the pools exist."""
    built = []
    with _lock:
        global _groq_client, _ollama_client
        if _groq_client is None:
            _groq_client = _build_groq()
            built.append("groq_pool")
        if _ollama_client is None:
            _ollama_client = _build_ollama()
            built.append("ollama")
    if built:
        logger.info("vision clients initialized (built once, never rebuilt): %s", ", ".join(built))


def reload_clients(db):
    """Rebuild the only config-dependent vision client: the **Gemini** model. The Groq pool
    and Ollama client are built once by init_clients and never appear here — Groq's key is
    injected per request (the SDK reads it per call, and meal_service already fetches the key
    via config.get_api_key), and Ollama is keyless. Gemini is the exception: google-generativeai
    0.8.3 bakes the key+model into the client and has no per-request key (`genai.configure` is
    process-global and resets the cached gRPC transport), so it's torn down and rebuilt on a
    key/model change.

    Called once at startup (core.lifespan) and after every PUT /api/config (routers.config).
    The lock serializes the rare rebuild; the dispatch hot path reads the globals lock-free."""
    init_clients()  # ensure the build-once pools exist (idempotent; no-op once warm)
    _, model = config.get_vision_config(db)
    gemini_key = config.get_value(db, "gemini_api_key")
    with _lock:
        global _gemini_model
        _gemini_model = _build_gemini(gemini_key, model) if gemini_key else None
    logger.info(
        "vision config applied (gemini=%s [rebuilt], model=%s)",
        _gemini_model is not None,
        model,
    )


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


# Provider functions return (parsed_result, raw_response_text) so the caller can log the
# model's raw output uniformly. They share a fixed signature
# (image_bytes, prompt, model, api_key) for uniform dispatch. The pooled client is built once
# (init_clients / reload_clients) — no per-call construction. `api_key` is the per-request key
# for Groq (the SDK keys via an Authorization header it reads per call); Gemini bakes its key
# into _gemini_model at build time and Ollama is keyless, so both ignore it.
def _gemini_analyze(image_bytes: bytes, prompt: str, model: str, api_key: str) -> tuple[dict, str]:
    gen_model = _gemini_model
    if gen_model is None:
        raise RuntimeError("Gemini client not initialized — set the Gemini API key in Settings.")
    image_part = {"mime_type": "image/jpeg", "data": image_bytes}
    response = gen_model.generate_content(
        [prompt, image_part],
        request_options={"timeout": CALL_TIMEOUT},
    )
    raw = response.text
    return _parse_compact(raw), raw


def _groq_analyze(image_bytes: bytes, prompt: str, model: str, api_key: str) -> tuple[dict, str]:
    client = _groq_client
    if client is None:
        raise RuntimeError("Groq client not initialized.")
    if not api_key:
        raise RuntimeError("Groq API key not set — set the Groq API key in Settings.")
    b64 = base64.b64encode(image_bytes).decode()
    # Inject the key per request: with_options returns a lightweight copy that REUSES the
    # pooled httpx client (only the auth header differs), so the connection pool is never
    # rebuilt and the key never lives on the shared global client.
    response = client.with_options(api_key=api_key).chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
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


def _ollama_analyze(image_bytes: bytes, prompt: str, model: str, api_key: str) -> tuple[dict, str]:
    """Local vision via the official Ollama client (no API key). Mirrors _groq_analyze:
    the image is passed as raw bytes (the client base64-encodes it), `format="json"` is
    plain JSON mode like Groq's response_format — the current qwen3-vl models keep our
    {meal_name,type,confidence,dishes:[...]} shape from the prompt alone (verified on the
    4B and 8B), so no explicit JSON schema is needed; temperature 0 for determinism."""
    client = _ollama_client
    if client is None:
        raise RuntimeError("Ollama client not initialized.")
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
    "gemini": _gemini_analyze,
    "groq": _groq_analyze,
    "ollama": _ollama_analyze,
}


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

    analyze = PROVIDERS.get(provider or DEFAULT_PROVIDER, _gemini_analyze)

    logger.info(
        "request -> provider=%s model=%s | image=%dB | note=%r",
        provider,
        model,
        len(image_bytes),
        (user_note or "")[:120],
    )

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            result, raw = analyze(image_bytes, prompt, model, api_key)
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
