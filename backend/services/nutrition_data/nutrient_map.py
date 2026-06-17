"""USDA FoodData Central nutrient IDs -> our schema keys (values are per 100g)."""

FDC_NUTRIENT_MAP = {
    1008: "calories",  # Energy (kcal)
    1003: "protein_g",
    1005: "carbs_g",  # Carbohydrate, by difference
    1004: "fat_g",  # Total lipid (fat)
    1079: "fiber_g",  # Fiber, total dietary
    2000: "sugar_g",  # Total Sugars
    1093: "sodium_mg",
    1106: "vitamin_a_mcg",  # Vitamin A, RAE
    1114: "vitamin_d_mcg",  # Vitamin D (D2 + D3)
    1109: "vitamin_e_mg",  # Vitamin E (alpha-tocopherol)
    1185: "vitamin_k_mcg",  # Vitamin K (phylloquinone)
    1162: "vitamin_c_mg",  # Vitamin C, total ascorbic acid
    1165: "vitamin_b1_mg",  # Thiamin
    1166: "vitamin_b2_mg",  # Riboflavin
    1167: "vitamin_b3_mg",  # Niacin
    1175: "vitamin_b6_mg",  # Vitamin B-6
    1178: "vitamin_b12_mcg",  # Vitamin B-12
    1177: "folate_mcg",  # Folate, total
    1087: "calcium_mg",
    1089: "iron_mg",
    1090: "magnesium_mg",
    1092: "potassium_mg",
    1095: "zinc_mg",
    1091: "phosphorus_mg",
    # Lipid panel (well-covered in FNDDS) + extra minerals/other.
    1258: "saturated_fat_g",  # Fatty acids, total saturated
    1292: "mono_fat_g",  # Fatty acids, total monounsaturated
    1293: "poly_fat_g",  # Fatty acids, total polyunsaturated
    1253: "cholesterol_mg",
    1103: "selenium_mcg",  # Selenium, Se
    1098: "copper_mg",  # Copper, Cu
    1180: "choline_mg",  # Choline, total
    1057: "caffeine_mg",
}

# Energy is sometimes reported under Atwater factors instead of 1008.
ENERGY_FALLBACK_IDS = (2047, 2048)

# Omega-3 (EPA + DHA) is the sum of two USDA nutrients, both in grams per 100g.
# A plain id->key map entry can't sum (extraction assigns, not accumulates), so these
# are handled with a dedicated summation in usda_service._extract_per_100g and kept by
# build_usda_db.py via KEEP_NUTRIENT_IDS. ALA (1404) is excluded deliberately: FNDDS
# carries it for 0 foods, so it would read 0 on every matched dish.
OMEGA3_IDS = (1278, 1272)  # EPA (20:5 n-3), DHA (22:6 n-3) -> omega3_g
