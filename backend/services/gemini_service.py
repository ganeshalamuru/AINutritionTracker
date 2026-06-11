import json
import os
import re
import google.generativeai as genai

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
        "vitamin_a_mcg": 120, "vitamin_d_mcg": 1.2, "vitamin_e_mg": 2.1,
        "vitamin_k_mcg": 35, "vitamin_c_mg": 18, "vitamin_b1_mg": 0.4,
        "vitamin_b2_mg": 0.3, "vitamin_b3_mg": 14, "vitamin_b6_mg": 1.1,
        "vitamin_b12_mcg": 0.9, "folate_mcg": 45, "calcium_mg": 55,
        "iron_mg": 2.8, "magnesium_mg": 62, "potassium_mg": 520,
        "zinc_mg": 3.2, "phosphorus_mg": 340
    },
    "notes": "Mock data — Gemini not called"
}

NUTRITION_PROMPT = """Analyze this food/meal image and return nutrition information as valid JSON only.
No markdown, no explanation - pure JSON only.

Return this exact structure:
{
  "meal_name": "descriptive meal name",
  "meal_type": "breakfast|lunch|dinner|snack",
  "confidence": "high|medium|low",
  "estimated_serving": "e.g. 1 plate (~350g)",
  "macros": {
    "calories": 0,
    "protein_g": 0,
    "carbs_g": 0,
    "fat_g": 0,
    "fiber_g": 0,
    "sugar_g": 0,
    "sodium_mg": 0
  },
  "micros": {
    "vitamin_a_mcg": 0,
    "vitamin_d_mcg": 0,
    "vitamin_e_mg": 0,
    "vitamin_k_mcg": 0,
    "vitamin_c_mg": 0,
    "vitamin_b1_mg": 0,
    "vitamin_b2_mg": 0,
    "vitamin_b3_mg": 0,
    "vitamin_b6_mg": 0,
    "vitamin_b12_mcg": 0,
    "folate_mcg": 0,
    "calcium_mg": 0,
    "iron_mg": 0,
    "magnesium_mg": 0,
    "potassium_mg": 0,
    "zinc_mg": 0,
    "phosphorus_mg": 0
  },
  "notes": "any notes about estimation accuracy"
}

Rules:
- Use 0 for nutrients you cannot estimate (never null or unknown)
- Base estimates on typical serving sizes visible in the image
- If multiple dishes are visible, sum all nutrients
- confidence: high=clearly identifiable dish, medium=probable, low=unclear"""


def analyze_meal_image(image_bytes: bytes, api_key: str) -> dict:
    if os.environ.get("MOCK_GEMINI", "").lower() in ("1", "true"):
        print("[mock] Returning mock Gemini response")
        return MOCK_RESPONSE

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-3.5-flash")

    image_part = {"mime_type": "image/jpeg", "data": image_bytes}
    response = model.generate_content([NUTRITION_PROMPT, image_part])

    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    return json.loads(text)
