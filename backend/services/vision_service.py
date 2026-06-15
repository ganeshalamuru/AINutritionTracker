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
import requests

from core import config
from core.config import DEFAULT_MODEL, DEFAULT_PROVIDER
from core.logging_config import configure_logging

# Logger for all model traffic. Shares the app's timestamped formatter (configured
# here too so logs still show when this module is imported standalone, e.g. tests).
configure_logging()
logger = logging.getLogger("nutriai.vision")

# --- shared vision clients ---
#
# A vision client carries its own HTTP connection pool, so we build it ONCE per process
# and reuse it across every /analyze. Following FastAPI's documented pattern for shared
# resources, the registry is populated in the app lifespan (core.lifespan calls
# reload_clients at startup) and rebuilt only when a key/provider/model changes in
# config (routers.config calls reload_clients after PUT /api/config). The lock serializes
# those rare rebuilds; the request hot path (_groq_analyze / _gemini_analyze) just reads
# the global, which is atomic under the GIL — no per-call lock or key comparison.
_lock = threading.Lock()
_groq_client = None  # built from groq_api_key
_gemini_model = None  # built from (gemini_api_key, vision_model)


def _build_groq(api_key: str):
    from groq import Groq  # lazy: keep the module importable without the SDK installed

    return Groq(api_key=api_key)


def _build_gemini(api_key: str, model: str):
    genai.configure(api_key=api_key)  # process-global key (matches the one-key reality)
    return genai.GenerativeModel(
        model,
        generation_config={"max_output_tokens": 1024, "temperature": 0},
    )


def reload_clients(db):
    """(Re)build the vision provider clients from current config. Called once at startup
    (core.lifespan) and again after every PUT /api/config. A client is built for each
    provider that has a key, so switching provider in Settings is ready immediately. The
    lock serializes rebuilds; dispatch reads the resulting globals without locking."""
    _, model = config.get_vision_config(db)
    groq_key = config.get_value(db, "groq_api_key")
    gemini_key = config.get_value(db, "gemini_api_key")
    with _lock:
        global _groq_client, _gemini_model
        _groq_client = _build_groq(groq_key) if groq_key else None
        _gemini_model = _build_gemini(gemini_key, model) if gemini_key else None
    logger.info(
        "vision clients reloaded (groq=%s, gemini=%s, model=%s)",
        _groq_client is not None,
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

# Ollama structured-output schema for the response. The cloud models (Llama 4 Scout /
# Gemini) follow the prompt's shape from `format: "json"` alone, but a local 4B collapses
# a single-dish photo to a bare {name,total_grams,components} object and drops the
# {meal_name,type,confidence,dishes:[...]} wrapper — so _parse_compact finds no `dishes`
# array and returns zero dishes. Passing the schema constrains decoding to the exact
# wrapper; the model only fills the values.
_OLLAMA_FORMAT = {
    "type": "object",
    "properties": {
        "meal_name": {"type": "string"},
        "type": {"type": "string"},
        "confidence": {"type": "string"},
        "dishes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "total_grams": {"type": "number"},
                    "components": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string"},
                                "usda_name": {"type": "string"},
                                "grams": {"type": "number"},
                            },
                            "required": ["item", "usda_name", "grams"],
                        },
                    },
                },
                "required": ["name", "total_grams", "components"],
            },
        },
    },
    "required": ["meal_name", "type", "confidence", "dishes"],
}

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


# Provider functions return (parsed_result, raw_response_text) so the caller can
# log the model's raw output uniformly. They read the shared client built by
# reload_clients (no per-call construction) — `model` is passed through for logging/Groq;
# the Gemini model is already baked into _gemini_model at build time.
def _gemini_analyze(image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
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


def _groq_analyze(image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
    client = _groq_client
    if client is None:
        raise RuntimeError("Groq client not initialized — set the Groq API key in Settings.")
    b64 = base64.b64encode(image_bytes).decode()
    response = client.chat.completions.create(
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


def _ollama_analyze(image_bytes: bytes, prompt: str, model: str) -> tuple[dict, str]:
    """Local vision via the Ollama daemon (no API key, no client to pre-build — it's a
    stateless HTTP endpoint on the machine). Mirrors _groq_analyze's shape: image goes in
    as base64, `format` carries the response JSON schema so decoding is constrained to our
    {meal_name,type,confidence,dishes:[...]} shape (a 4B drops the wrapper otherwise),
    temperature 0 for determinism."""
    b64 = base64.b64encode(image_bytes).decode()
    response = requests.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "stream": False,
            "format": _OLLAMA_FORMAT,
            "options": {"temperature": 0, "num_ctx": OLLAMA_NUM_CTX},
            "messages": [{"role": "user", "content": prompt, "images": [b64]}],
        },
        timeout=OLLAMA_TIMEOUT,
    )
    response.raise_for_status()
    raw = response.json().get("message", {}).get("content") or ""
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
            result, raw = analyze(image_bytes, prompt, model)
            elapsed = time.monotonic() - start
            logger.info(
                "response <- provider=%s model=%s | %.2fs | raw=%s",
                provider,
                model,
                elapsed,
                (raw or "").strip(),
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
