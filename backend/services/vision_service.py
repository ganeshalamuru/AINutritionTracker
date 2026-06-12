"""Vision / perception stage (Stage 1 of the two-stage nutrition pipeline).

Despite the historical names floating around the project, this module is provider-
agnostic: it dispatches a meal photo to whichever vision model is configured (Groq,
Gemini, or a future Ollama) and returns ONLY a decomposed ingredient list — it does
NOT estimate nutrients (the model hallucinated those). The real per-100g numbers come
from the USDA lookup in usda_service.py.
"""
import base64
import json
import logging
import os
import re
import time
import google.generativeai as genai

from core.config import DEFAULT_PROVIDER, DEFAULT_MODEL
from core.logging_config import configure_logging

# Logger for all model traffic. Shares the app's timestamped formatter (configured
# here too so logs still show when this module is imported standalone, e.g. tests).
configure_logging()
logger = logging.getLogger("nutriai.vision")

# Per-call timeout (seconds) and retry budget. The app used to hang forever when
# the model never responded — cap each call and retry at most once.
CALL_TIMEOUT = 15
MAX_RETRIES = 1  # one extra attempt after the first failure

# Mock vision output: the dish list (macros/micros come from the lookup stage, which
# short-circuits to canned values under MOCK_GEMINI — see usda_service).
MOCK_RESPONSE = {
    "meal_name": "Grilled Chicken with Rice and Vegetables",
    "meal_type": "lunch",
    "confidence": "high",
    "dishes": [
        {"name": "grilled chicken", "grams": 150,
         "items": [{"food": "grilled chicken breast", "grams": 150}]},
        {"name": "white rice", "grams": 180,
         "items": [{"food": "white rice, cooked", "grams": 180}]},
        {"name": "mixed vegetables", "grams": 120,
         "items": [{"food": "mixed vegetables, cooked", "grams": 120}]},
    ],
}

NUTRITION_PROMPT = """Identify the dishes in this meal photo. Output ONLY compact JSON, no markdown or prose:
{"n":"meal name","t":"breakfast|lunch|dinner|snack","c":"high|medium|low","d":[{"n":"dish","g":grams,"i":[{"f":"ingredient","g":grams},...]}]}

- One entry per distinct dish/food; never merge dishes. "n"=common dish name, "g"=its total edible grams in the photo. Estimate grams conservatively — when unsure, lean low rather than high.
- "i"=base-ingredient fallback (used only if the dish isn't found): plain single foods (grains, dals, vegetables, dairy, meat, nuts, oil, sugar, spices) with grams.
- Do NOT estimate calories or nutrients. "c": high=clear, medium=probable, low=unclear.

Examples:
idli -> {"n":"idli","g":160,"i":[{"f":"rice","g":90},{"f":"urad dal","g":30}]}
sambar -> {"n":"sambar","g":150,"i":[{"f":"toor dal","g":30},{"f":"mixed vegetables","g":60},{"f":"tamarind","g":5},{"f":"vegetable oil","g":5}]}"""


def _is_quota_error(err: str) -> bool:
    """Daily-quota exhaustion — not worth retrying (won't recover within the call)."""
    err = err.lower()
    return ("quota" in err or "daily" in err or "resource_exhausted" in err
            or "per_day" in err or "requests_per_day" in err)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _parse_items(arr) -> list[dict]:
    """Keep well-formed {food, grams} entries from the model's ingredient list.
    Tolerant of junk: non-dict entries, missing/blank names, or bad weights are
    dropped; a non-numeric weight defaults to 0 (contributes nothing downstream)."""
    out = []
    if not isinstance(arr, list):
        return out
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        food = (entry.get("f") or "").strip()
        if not food:
            continue
        grams = entry.get("g")
        out.append({"food": food, "grams": grams if _is_number(grams) else 0})
    return out


def _parse_dishes(arr) -> list[dict]:
    """Keep well-formed dishes from the model's `d` list. Each dish is
    {name, grams, items}: a named dish, its estimated portion grams, and its
    base-ingredient breakdown (parsed by _parse_items, used as a lookup fallback).
    Tolerant of junk: non-dict entries and nameless dishes are dropped; a bad grams
    value defaults to 0."""
    out = []
    if not isinstance(arr, list):
        return out
    for entry in arr:
        if not isinstance(entry, dict):
            continue
        name = (entry.get("n") or "").strip()
        if not name:
            continue
        grams = entry.get("g")
        out.append({
            "name": name,
            "grams": grams if _is_number(grams) else 0,
            "items": _parse_items(entry.get("i")),
        })
    return out


def _parse_compact(text: str) -> dict:
    """Strip fences, parse the compact JSON, and remap to the named schema. The
    vision stage returns a list of dishes (each with a fallback ingredient breakdown),
    not nutrient numbers."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return {
        "meal_name": data.get("n") or "Unknown meal",
        "meal_type": data.get("t") or "snack",
        "confidence": data.get("c") or "medium",
        "dishes": _parse_dishes(data.get("d")),
    }


# Provider functions return (parsed_result, raw_response_text) so the caller can
# log the model's raw output uniformly.
def _gemini_analyze(image_bytes: bytes, api_key: str, prompt: str, model: str) -> tuple[dict, str]:
    genai.configure(api_key=api_key)
    gen_model = genai.GenerativeModel(
        model,
        generation_config={"max_output_tokens": 512, "temperature": 0},
    )
    image_part = {"mime_type": "image/jpeg", "data": image_bytes}
    response = gen_model.generate_content(
        [prompt, image_part],
        request_options={"timeout": CALL_TIMEOUT},
    )
    raw = response.text
    return _parse_compact(raw), raw


def _groq_analyze(image_bytes: bytes, api_key: str, prompt: str, model: str) -> tuple[dict, str]:
    from groq import Groq

    client = Groq(api_key=api_key)
    b64 = base64.b64encode(image_bytes).decode()
    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        temperature=0,
        max_tokens=512,
        response_format={"type": "json_object"},
        timeout=CALL_TIMEOUT,
    )
    raw = response.choices[0].message.content or ""
    return _parse_compact(raw), raw


def _ollama_analyze(*args, **kwargs) -> tuple[dict, str]:
    raise RuntimeError("Ollama provider is not configured yet.")


PROVIDERS = {
    "gemini": _gemini_analyze,
    "groq": _groq_analyze,
    "ollama": _ollama_analyze,
}


def analyze_meal_image(
    image_bytes: bytes,
    api_key: str,
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
        provider, model, len(image_bytes), (user_note or "")[:120],
    )

    last_err = None
    for attempt in range(MAX_RETRIES + 1):
        start = time.monotonic()
        try:
            result, raw = analyze(image_bytes, api_key, prompt, model)
            elapsed = time.monotonic() - start
            logger.info(
                "response <- provider=%s model=%s | %.2fs | raw=%s",
                provider, model, elapsed, (raw or "").strip(),
            )
            return result
        except Exception as e:
            elapsed = time.monotonic() - start
            last_err = e
            # Daily quota won't recover within this request — fail fast.
            if _is_quota_error(str(e)):
                logger.error(
                    "error <- provider=%s model=%s | %.2fs | quota: %s: %s",
                    provider, model, elapsed, type(e).__name__, e,
                )
                raise
            # Timeout / per-minute rate / transient — retry once with a short backoff.
            if attempt < MAX_RETRIES:
                logger.warning(
                    "retry %d/%d <- provider=%s model=%s | %.2fs | %s: %s",
                    attempt + 1, MAX_RETRIES, provider, model, elapsed, type(e).__name__, e,
                )
                time.sleep(1.5)
                continue
            logger.error(
                "error <- provider=%s model=%s | %.2fs | %s: %s",
                provider, model, elapsed, type(e).__name__, e,
            )
            raise last_err
