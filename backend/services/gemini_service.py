import base64
import json
import logging
import os
import re
import time
import google.generativeai as genai

from logging_config import configure_logging

# Logger for all model traffic. Shares the app's timestamped formatter (configured
# here too so logs still show when this module is imported standalone, e.g. tests).
configure_logging()
logger = logging.getLogger("nutriai.vision")

# Default vision provider/model. Groq's free tier gives ~1,000 RPD / 6K TPM (vs
# Google free tier's ~20 RPD on Flash, or Gemma's 383 TPM that can't fit a single
# image request) plus the fastest inference. Llama 4 Scout is natively multimodal.
DEFAULT_PROVIDER = "groq"
DEFAULT_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"

# Per-call timeout (seconds) and retry budget. The app used to hang forever when
# the model never responded — cap each call and retry at most once.
CALL_TIMEOUT = 15
MAX_RETRIES = 1  # one extra attempt after the first failure

# Macros are a fixed-order array (always all 7). Micros are a variable object —
# the model reports only the nutrients notable for THIS meal, keyed by name from
# the full allowed list. Both remap to the named schema the rest of the app uses.
MACRO_KEYS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]
ALL_MICRO_KEYS = [
    "vitamin_a_mcg", "vitamin_d_mcg", "vitamin_e_mg", "vitamin_k_mcg", "vitamin_c_mg",
    "vitamin_b1_mg", "vitamin_b2_mg", "vitamin_b3_mg", "vitamin_b6_mg", "vitamin_b12_mcg",
    "folate_mcg", "calcium_mg", "iron_mg", "magnesium_mg", "potassium_mg",
    "zinc_mg", "phosphorus_mg",
]

# Mock is returned in the final NAMED form (bypasses compaction/remap).
MOCK_RESPONSE = {
    "meal_name": "Grilled Chicken with Rice and Vegetables",
    "meal_type": "lunch",
    "confidence": "high",
    "estimated_serving": "1 plate (~450g)",
    "macros": {
        "calories": 520, "protein_g": 42, "carbs_g": 55, "fat_g": 12,
        "fiber_g": 6, "sugar_g": 4, "sodium_mg": 480
    },
    "micros": {
        "vitamin_c_mg": 18, "vitamin_d_mcg": 1.2, "vitamin_b12_mcg": 0.9,
        "folate_mcg": 45, "calcium_mg": 55, "iron_mg": 2.8,
        "magnesium_mg": 62, "potassium_mg": 520,
    },
    "notes": "Mock data — model not called"
}

NUTRITION_PROMPT = """Analyze this food/meal image and return ONLY compact JSON. No markdown, no prose.

Schema (return exactly this shape):
{"n":"meal name","t":"breakfast|lunch|dinner|snack","c":"high|medium|low","m":[calories,protein_g,carbs_g,fat_g,fiber_g,sugar_g,sodium_mg],"u":{"micro_key":amount, ...}}

Rules:
- "m" is exactly 7 numbers in the order shown above (use 0 if you cannot estimate one).
- "u" is an OBJECT containing ONLY the micronutrients present in notable amounts for THIS meal
  (usually 3-8 of them). Omit any that are negligible or zero. Use these EXACT key names:
  vitamin_a_mcg, vitamin_d_mcg, vitamin_e_mg, vitamin_k_mcg, vitamin_c_mg, vitamin_b1_mg,
  vitamin_b2_mg, vitamin_b3_mg, vitamin_b6_mg, vitamin_b12_mcg, folate_mcg, calcium_mg,
  iron_mg, magnesium_mg, potassium_mg, zinc_mg, phosphorus_mg.
- Base estimates on typical serving sizes visible in the image. If multiple dishes are visible, sum all nutrients.
- Sodium is in mg. c: high=clearly identifiable dish, medium=probable, low=unclear."""


def _is_quota_error(err: str) -> bool:
    """Daily-quota exhaustion — not worth retrying (won't recover within the call)."""
    err = err.lower()
    return ("quota" in err or "daily" in err or "resource_exhausted" in err
            or "per_day" in err or "requests_per_day" in err)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _arr_to_dict(arr, keys) -> dict:
    """Map a fixed-order numeric array back to named keys. Tolerant of a wrong
    length or non-numeric entries — missing/invalid values default to 0."""
    out = {k: 0 for k in keys}
    if isinstance(arr, list):
        for i, key in enumerate(keys):
            if i < len(arr) and _is_number(arr[i]):
                out[key] = arr[i]
    return out


def _obj_to_micros(obj) -> dict:
    """Keep only known micro keys with numeric values from the model's object.
    Unknown keys / junk are ignored; unreported micros default to 0 downstream."""
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if k in ALL_MICRO_KEYS and _is_number(v)}


def _parse_compact(text: str) -> dict:
    """Strip fences, parse the compact JSON, and remap to the named schema."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    return {
        "meal_name": data.get("n") or "Unknown meal",
        "meal_type": data.get("t") or "snack",
        "confidence": data.get("c") or "medium",
        "macros": _arr_to_dict(data.get("m"), MACRO_KEYS),
        "micros": _obj_to_micros(data.get("u")),
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
