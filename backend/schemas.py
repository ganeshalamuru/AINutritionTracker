from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# --- Enums (constrain the small fixed vocabularies) ---


class MealType(StrEnum):
    breakfast = "breakfast"
    lunch = "lunch"
    dinner = "dinner"
    snack = "snack"


class Confidence(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"


class IngredientStatus(StrEnum):
    matched = "matched"
    unmatched = "unmatched"
    skipped = "skipped"
    not_looked_up = "not_looked_up"


class VisionProvider(StrEnum):
    groq = "groq"
    gemini = "gemini"
    ollama = "ollama"


# Reusable PIN field: exactly 4 digits.
PinField = Field(pattern=r"^\d{4}$", description="4-digit PIN")


# --- Profiles ---


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    pin: str = PinField
    avatar_color: str | None = "#22c55e"


class ProfileOut(BaseModel):
    id: int
    name: str
    avatar_color: str
    calorie_goal: int = 2000

    model_config = {"from_attributes": True}


class ProfileGoalUpdate(BaseModel):
    calorie_goal: int = Field(ge=500, le=10000)


class PinVerify(BaseModel):
    profile_id: int
    pin: str = PinField


# --- Macros ---


class MacrosData(BaseModel):
    calories: float = Field(default=0, ge=0)
    protein_g: float = Field(default=0, ge=0)
    carbs_g: float = Field(default=0, ge=0)
    fat_g: float = Field(default=0, ge=0)
    fiber_g: float = Field(default=0, ge=0)
    sugar_g: float = Field(default=0, ge=0)
    sodium_mg: float = Field(default=0, ge=0)


# --- Micros ---


class MicrosData(BaseModel):
    vitamin_a_mcg: float = Field(default=0, ge=0)
    vitamin_d_mcg: float = Field(default=0, ge=0)
    vitamin_e_mg: float = Field(default=0, ge=0)
    vitamin_k_mcg: float = Field(default=0, ge=0)
    vitamin_c_mg: float = Field(default=0, ge=0)
    vitamin_b1_mg: float = Field(default=0, ge=0)
    vitamin_b2_mg: float = Field(default=0, ge=0)
    vitamin_b3_mg: float = Field(default=0, ge=0)
    vitamin_b6_mg: float = Field(default=0, ge=0)
    vitamin_b12_mcg: float = Field(default=0, ge=0)
    folate_mcg: float = Field(default=0, ge=0)
    calcium_mg: float = Field(default=0, ge=0)
    iron_mg: float = Field(default=0, ge=0)
    magnesium_mg: float = Field(default=0, ge=0)
    potassium_mg: float = Field(default=0, ge=0)
    zinc_mg: float = Field(default=0, ge=0)
    phosphorus_mg: float = Field(default=0, ge=0)


# --- Meals ---


class IngredientBreakdown(BaseModel):
    food: str
    grams: float = Field(default=0, ge=0)
    # USDA outcome: matched | unmatched | skipped (over the lookup cap) |
    # not_looked_up (its dish matched whole, so the ingredient wasn't searched)
    status: IngredientStatus = IngredientStatus.matched
    # This ingredient's own nutrient subtotal at its `grams`. Non-zero only for a resolved
    # ingredient of a *decomposed* dish; 0 for not_looked_up (matched dish), unmatched, and
    # skipped. Lets the client rescale or remove a single ingredient without re-querying USDA.
    # Across a decomposed dish, Σ ingredients == the dish subtotal (an invariant).
    macros: MacrosData = Field(default_factory=MacrosData)
    micros: MicrosData = Field(default_factory=MicrosData)


class DishBreakdown(BaseModel):
    name: str
    grams: float = Field(default=0, ge=0)
    matched: bool = False  # the whole dish matched in USDA (ingredients not looked up)
    # This dish's own nutrient subtotal; summed across dishes it equals the meal totals.
    # Lets the client rescale a dish by its edited portion without re-querying USDA.
    macros: MacrosData = Field(default_factory=MacrosData)
    micros: MicrosData = Field(default_factory=MicrosData)
    ingredients: list[IngredientBreakdown] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    # meal_type/confidence are normalized to these enums in vision_service._parse_compact
    # before reaching here, so a surprise model output can never fail response validation.
    meal_name: str
    meal_type: MealType
    confidence: Confidence
    estimated_serving: str | None = None
    macros: MacrosData
    micros: MicrosData
    dishes: list[DishBreakdown] = Field(default_factory=list)
    unmatched: list[str] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    temp_image_token: str | None = None
    notes: str | None = None


class MealLogRequest(BaseModel):
    profile_id: int
    meal_name: str = Field(min_length=1)
    meal_type: MealType = MealType.snack
    notes: str | None = None
    keep_image: bool = False
    temp_image_token: str | None = None
    macros: MacrosData
    micros: MicrosData


class LogGroupRequest(BaseModel):
    group_id: str
    meals: list[MealLogRequest]


class MealLogResponse(BaseModel):
    id: int
    logged_at: datetime


class LogGroupResponse(BaseModel):
    group_id: str
    meal_ids: list[int]


class MealPatch(BaseModel):
    meal_name: str | None = Field(default=None, min_length=1)
    meal_type: MealType | None = None
    notes: str | None = None


class MealSummary(BaseModel):
    item_type: Literal["meal"] = "meal"
    id: int
    meal_name: str
    meal_type: str
    logged_at: datetime
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0
    has_image: bool
    group_id: str | None = None

    model_config = {"from_attributes": True}


class MealSubSummary(BaseModel):
    id: int
    meal_name: str
    meal_type: str
    logged_at: datetime
    macros: MacrosData


class MealGroupSummary(BaseModel):
    item_type: Literal["group"] = "group"
    group_id: str
    logged_at: datetime
    sub_meals: list[MealSubSummary]
    total_macros: MacrosData
    total_micros: MicrosData = Field(default_factory=MicrosData)


TimelineItem = Annotated[MealGroupSummary | MealSummary, Field(discriminator="item_type")]


class MealDetail(BaseModel):
    id: int
    meal_name: str
    meal_type: str
    logged_at: datetime
    notes: str | None
    has_image: bool
    macros: MacrosData
    micros: MicrosData

    model_config = {"from_attributes": True}


class TimelineResponse(BaseModel):
    items: list[TimelineItem]
    total: int
    page: int
    limit: int


# --- Nutrition Summaries ---


class DailySummary(BaseModel):
    date: str
    meal_count: int
    totals: dict
    meals: list[MealSummary]


class DailyBreakdown(BaseModel):
    date: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MonthlySummary(BaseModel):
    year: int
    month: int
    daily_breakdown: list[DailyBreakdown]
    monthly_averages: dict
    monthly_totals: dict
    days_logged: int


# --- Config ---


class ConfigUpdate(BaseModel):
    gemini_api_key: str | None = None
    groq_api_key: str | None = None
    usda_api_key: str | None = None
    nutrition_source: Literal["online", "offline"] | None = None
    vision_provider: VisionProvider | None = None
    vision_model: str | None = None


class ConfigStatus(BaseModel):
    gemini_api_key_set: bool
    groq_api_key_set: bool
    usda_api_key_set: bool
    nutrition_source: str
    vision_provider: str
    vision_model: str


# --- Foods / Admin query APIs ---


class FoodSummary(BaseModel):
    """A ranked hit from the offline USDA search index (usda_local.db)."""

    fdc_id: int
    description: str
    data_type: str
    score: float = 0


class FoodDetail(BaseModel):
    """A single USDA food with its per-100g macro/micro profile."""

    fdc_id: int
    description: str
    data_type: str
    macros: MacrosData
    micros: MicrosData


class FoodCacheEntry(BaseModel):
    """One row of the food_cache table (a remembered USDA lookup)."""

    query: str
    fdc_id: int | None = None
    nutrients: dict
    fetched_at: float | None = None


class AdminMeal(BaseModel):
    """Flat admin view of a logged meal with its nutrient subtotals (no profile PIN)."""

    id: int
    profile_id: int
    meal_name: str
    meal_type: str
    logged_at: datetime
    macros: MacrosData
    micros: MicrosData


class AdminConfigEntry(BaseModel):
    """An app_config row; secret (`*_api_key`) values are redacted in `value`."""

    key: str
    value: str
    is_secret: bool = False


class TableInfo(BaseModel):
    name: str
    rows: int


class SqlQueryRequest(BaseModel):
    sql: str = Field(min_length=1, description="A single read-only SELECT/WITH statement")


class SqlQueryResult(BaseModel):
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool = False


# --- Generic ---


class OkResponse(BaseModel):
    ok: bool = True
