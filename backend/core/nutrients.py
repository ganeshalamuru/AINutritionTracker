"""Single source of truth for the nutrient schema.

The 7 macros and 17 micros are listed here ONCE; every other module imports these
lists instead of re-declaring them (they used to be duplicated in the vision service,
the USDA service, and the nutrition router). Also holds the small ORM<->schema
conversion and summation helpers those modules all need.

Depends only on `schemas` (a leaf module), so importing this never creates a cycle.
"""

from schemas import MacrosData, MicrosData

MACRO_KEYS = ["calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg"]
MICRO_KEYS = [
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
]


def to_macros_data(macros) -> MacrosData:
    """ORM Macros row (or None) -> MacrosData, coercing missing/NULL values to 0."""
    if not macros:
        return MacrosData()
    return MacrosData(**{k: getattr(macros, k, 0) or 0 for k in MACRO_KEYS})


def to_micros_data(micros) -> MicrosData:
    """ORM Micros row (or None) -> MicrosData, coercing missing/NULL values to 0."""
    if not micros:
        return MicrosData()
    return MicrosData(**{k: getattr(micros, k, 0) or 0 for k in MICRO_KEYS})


def sum_macros(a: MacrosData, b: MacrosData) -> MacrosData:
    return MacrosData(**{k: getattr(a, k) + getattr(b, k) for k in MACRO_KEYS})


def sum_micros(a: MicrosData, b: MicrosData) -> MicrosData:
    return MicrosData(**{k: getattr(a, k) + getattr(b, k) for k in MICRO_KEYS})
