"""Single source of truth for the nutrient schema.

All 33 nutrients are listed here ONCE as a single flat set; every other module imports
this list instead of re-declaring it (it used to be duplicated in the vision service,
the USDA service, and the nutrition router). Also holds the small ORM<->schema
conversion and summation helpers those modules all need.

The backend makes **no** macro/micro distinction — it's a flat "standard nutrients"
bag. The macro / micro / fat-breakdown grouping is purely a *display* concern, made
only in the frontend (MacroRing, MicroGrid, FatBreakdown each pick their own keys).

Depends only on `schemas` (a leaf module), so importing this never creates a cycle.
"""

from schemas import NutrientsData

# Order: the 7 headline macros first, then vitamins/minerals/other, then the fat
# breakdown (saturated/mono/poly fat, cholesterol, omega-3). Order is storage-only —
# the frontend imposes its own display order — but is kept stable so the DB column
# layout and the macros->nutrients migration column-mapping stay obvious.
NUTRIENT_KEYS = [
    "calories",
    "protein_g",
    "carbs_g",
    "fat_g",
    "fiber_g",
    "sugar_g",
    "sodium_mg",
    "vitamin_a_mcg",
    "vitamin_d_mcg",
    "vitamin_e_mg",
    "vitamin_k_mcg",
    "vitamin_c_mg",
    "vitamin_b1_mg",
    "vitamin_b2_mg",
    "vitamin_b3_mg",
    "vitamin_b6_mg",
    "vitamin_b12_mcg",
    "folate_mcg",
    "calcium_mg",
    "iron_mg",
    "magnesium_mg",
    "potassium_mg",
    "zinc_mg",
    "phosphorus_mg",
    "selenium_mcg",
    "copper_mg",
    "choline_mg",
    "caffeine_mg",
    "saturated_fat_g",
    "mono_fat_g",
    "poly_fat_g",
    "cholesterol_mg",
    "omega3_g",
]


def to_nutrients_data(nutrients) -> NutrientsData:
    """ORM Nutrients row (or None) -> NutrientsData, coercing missing/NULL values to 0."""
    if not nutrients:
        return NutrientsData()
    return NutrientsData(**{k: getattr(nutrients, k, 0) or 0 for k in NUTRIENT_KEYS})


def sum_nutrients(a: NutrientsData, b: NutrientsData) -> NutrientsData:
    return NutrientsData(**{k: getattr(a, k) + getattr(b, k) for k in NUTRIENT_KEYS})
