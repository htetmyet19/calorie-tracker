import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class FoodItem(BaseModel):
    name: str = Field(description="Specific dish or food name, e.g. 'chicken biryani'")
    portion: str = Field(description="Human-readable portion, e.g. '1 plate', '2 rotis'")
    grams: float = Field(description="Estimated edible weight in grams")
    calories: float = Field(description="Estimated kcal for this portion")
    protein_g: float
    carbs_g: float
    fat_g: float
    confidence: Literal["low", "medium", "high"]


class MealAnalysis(BaseModel):
    """Shape we ask Gemini to return (structured output)."""
    is_food: bool = Field(description="False if the image does not show food or drink")
    items: list[FoodItem]
    notes: str = Field(description="Assumptions made, e.g. hidden oil, sauce, portion uncertainty")


class AnalyzeResponse(MealAnalysis):
    total_calories: float
    warnings: list[str]


class MealIn(BaseModel):
    eaten_at: str = Field(description="Local datetime, ISO format 'YYYY-MM-DDTHH:MM'")
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = "snack"
    items: list[FoodItem] = Field(min_length=1)

    @field_validator("eaten_at")
    @classmethod
    def _real_datetime(cls, v: str) -> str:
        try:
            parsed = datetime.datetime.strptime(v, "%Y-%m-%dT%H:%M")
            if parsed.strftime("%Y-%m-%dT%H:%M") != v:
                raise ValueError(v)
        except ValueError:
            raise ValueError("eaten_at must be a real datetime like 2026-10-31T08:00")
        return v


class MealOut(MealIn):
    id: int
    total_calories: float


class DayLog(BaseModel):
    date: str
    meals: list[MealOut]
    total_calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class RoleIn(BaseModel):
    role: Literal["client", "trainer"]
    display_name: str

    @field_validator("display_name")
    @classmethod
    def _name_length(cls, v: str) -> str:
        v = v.strip()
        if not 1 <= len(v) <= 80:
            raise ValueError("display_name must be 1-80 characters")
        return v


class ProfileOut(BaseModel):
    id: str
    role: str
    display_name: str


class SettingsIn(BaseModel):
    height_cm: float | None = Field(default=None, ge=120, le=230)
    weight_kg: float | None = Field(default=None, ge=30, le=300)
    age: int | None = Field(default=None, ge=18, le=100)
    sex: Literal["male", "female", "unspecified"] | None = None
    activity: Literal[1.2, 1.375, 1.55, 1.725, 1.9] | None = None
    weight_goal: Literal["lose", "maintain", "gain"] | None = None
    goal_kcal: int | None = Field(default=None, ge=500, le=9000)
    weight_unit: Literal["kg", "lb"] = "kg"
    reminders_enabled: bool = False


class SettingsOut(SettingsIn):
    goal_set_by: str | None = None


class WeightIn(BaseModel):
    weight_kg: float = Field(ge=30, le=300)


class WeightOut(BaseModel):
    logged_on: str
    weight_kg: float
