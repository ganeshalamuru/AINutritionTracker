from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


# --- Profiles ---

class ProfileCreate(BaseModel):
    name: str
    pin: str
    avatar_color: Optional[str] = "#22c55e"


class ProfileOut(BaseModel):
    id: int
    name: str
    avatar_color: str

    model_config = {"from_attributes": True}


class PinVerify(BaseModel):
    profile_id: int
    pin: str


# --- Macros ---

class MacrosData(BaseModel):
    calories: float = 0
    protein_g: float = 0
    carbs_g: float = 0
    fat_g: float = 0
    fiber_g: float = 0
    sugar_g: float = 0
    sodium_mg: float = 0


# --- Micros ---

class MicrosData(BaseModel):
    vitamin_a_mcg: float = 0
    vitamin_d_mcg: float = 0
    vitamin_e_mg: float = 0
    vitamin_k_mcg: float = 0
    vitamin_c_mg: float = 0
    vitamin_b1_mg: float = 0
    vitamin_b2_mg: float = 0
    vitamin_b3_mg: float = 0
    vitamin_b6_mg: float = 0
    vitamin_b12_mcg: float = 0
    folate_mcg: float = 0
    calcium_mg: float = 0
    iron_mg: float = 0
    magnesium_mg: float = 0
    potassium_mg: float = 0
    zinc_mg: float = 0
    phosphorus_mg: float = 0


# --- Meals ---

class AnalyzeResponse(BaseModel):
    meal_name: str
    meal_type: str
    confidence: str
    estimated_serving: Optional[str] = None
    macros: MacrosData
    micros: MicrosData
    temp_image_token: Optional[str] = None
    notes: Optional[str] = None


class MealLogRequest(BaseModel):
    profile_id: int
    meal_name: str
    meal_type: str = "snack"
    notes: Optional[str] = None
    keep_image: bool = False
    temp_image_token: Optional[str] = None
    macros: MacrosData
    micros: MicrosData


class MealLogResponse(BaseModel):
    id: int
    logged_at: datetime


class MealPatch(BaseModel):
    meal_name: Optional[str] = None
    meal_type: Optional[str] = None
    notes: Optional[str] = None


class MealSummary(BaseModel):
    id: int
    meal_name: str
    meal_type: str
    logged_at: datetime
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float
    has_image: bool

    model_config = {"from_attributes": True}


class MealDetail(BaseModel):
    id: int
    meal_name: str
    meal_type: str
    logged_at: datetime
    notes: Optional[str]
    has_image: bool
    macros: MacrosData
    micros: MicrosData

    model_config = {"from_attributes": True}


class TimelineResponse(BaseModel):
    items: List[MealSummary]
    total: int
    page: int
    limit: int


# --- Nutrition Summaries ---

class DailySummary(BaseModel):
    date: str
    meal_count: int
    totals: dict
    meals: List[MealSummary]


class DailyBreakdown(BaseModel):
    date: str
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class MonthlySummary(BaseModel):
    year: int
    month: int
    daily_breakdown: List[DailyBreakdown]
    monthly_averages: dict
    monthly_totals: dict
    days_logged: int


# --- Config ---

class ConfigUpdate(BaseModel):
    gemini_api_key: str
