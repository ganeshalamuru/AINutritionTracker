from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from core.database import Base


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    pin = Column(String(4), nullable=False)
    avatar_color = Column(String, default="#22c55e")
    calorie_goal = Column(Integer, default=2000, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    is_active = Column(Boolean, default=True)

    meals = relationship("Meal", back_populates="profile", cascade="all, delete-orphan")


class Meal(Base):
    __tablename__ = "meals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    profile_id = Column(Integer, ForeignKey("profiles.id"), nullable=False)
    meal_name = Column(String, nullable=False)
    meal_type = Column(String, default="snack")
    image_path = Column(String, nullable=True)
    group_id = Column(String, nullable=True, index=True)
    logged_at = Column(DateTime, default=lambda: datetime.now(UTC))
    notes = Column(Text, nullable=True)

    profile = relationship("Profile", back_populates="meals")
    nutrients = relationship(
        "Nutrients", back_populates="meal", uselist=False, cascade="all, delete-orphan"
    )


class Nutrients(Base):
    """Flat "standard nutrients" row, 1:1 with a meal. All 33 nutrients live together —
    the backend draws no macro/micro line (that's a display-only grouping in the frontend).
    Columns mirror core.nutrients.NUTRIENT_KEYS exactly. Replaces the former split
    Macros/Micros tables; existing rows are migrated in core.lifespan."""

    __tablename__ = "nutrients"

    id = Column(Integer, primary_key=True, autoincrement=True)
    meal_id = Column(Integer, ForeignKey("meals.id"), nullable=False, unique=True)
    # Headline macros.
    calories = Column(Float, default=0)
    protein_g = Column(Float, default=0)
    carbs_g = Column(Float, default=0)
    fat_g = Column(Float, default=0)
    fiber_g = Column(Float, default=0)
    sugar_g = Column(Float, default=0)
    sodium_mg = Column(Float, default=0)
    # Vitamins / minerals / other.
    vitamin_a_mcg = Column(Float, default=0)
    vitamin_d_mcg = Column(Float, default=0)
    vitamin_e_mg = Column(Float, default=0)
    vitamin_k_mcg = Column(Float, default=0)
    vitamin_c_mg = Column(Float, default=0)
    vitamin_b1_mg = Column(Float, default=0)
    vitamin_b2_mg = Column(Float, default=0)
    vitamin_b3_mg = Column(Float, default=0)
    vitamin_b6_mg = Column(Float, default=0)
    vitamin_b12_mcg = Column(Float, default=0)
    folate_mcg = Column(Float, default=0)
    calcium_mg = Column(Float, default=0)
    iron_mg = Column(Float, default=0)
    magnesium_mg = Column(Float, default=0)
    potassium_mg = Column(Float, default=0)
    zinc_mg = Column(Float, default=0)
    phosphorus_mg = Column(Float, default=0)
    selenium_mcg = Column(Float, default=0)
    copper_mg = Column(Float, default=0)
    choline_mg = Column(Float, default=0)
    caffeine_mg = Column(Float, default=0)
    # Fat breakdown (shown grouped under Fat in the UI).
    saturated_fat_g = Column(Float, default=0)
    mono_fat_g = Column(Float, default=0)
    poly_fat_g = Column(Float, default=0)
    cholesterol_mg = Column(Float, default=0)
    omega3_g = Column(Float, default=0)

    meal = relationship("Meal", back_populates="nutrients")


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
