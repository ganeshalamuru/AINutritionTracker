"""Canned per-meal totals returned in mock mode so the pipeline runs fully offline."""

MOCK_MACROS = {
    "calories": 520,
    "protein_g": 42,
    "carbs_g": 55,
    "fat_g": 12,
    "fiber_g": 6,
    "sugar_g": 4,
    "sodium_mg": 480,
}
MOCK_MICROS = {
    "vitamin_c_mg": 18,
    "vitamin_d_mcg": 1.2,
    "vitamin_b12_mcg": 0.9,
    "folate_mcg": 45,
    "calcium_mg": 55,
    "iron_mg": 2.8,
    "magnesium_mg": 62,
    "potassium_mg": 520,
    "selenium_mcg": 22,
    "copper_mg": 0.3,
    "choline_mg": 95,
    "caffeine_mg": 0,
    # Fat breakdown (sums under the meal's 12 g total fat).
    "saturated_fat_g": 3.2,
    "mono_fat_g": 5.1,
    "poly_fat_g": 2.4,
    "cholesterol_mg": 65,
    "omega3_g": 0.12,
}
