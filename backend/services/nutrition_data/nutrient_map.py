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
}

# Energy is sometimes reported under Atwater factors instead of 1008.
ENERGY_FALLBACK_IDS = (2047, 2048)
