import datetime
import re
import unicodedata
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator


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
    has_photo: bool = False
    photo_removed: bool = False  # the daily job removed the photo after 90 days


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
    # The weight the goal was worked out from; None for a goal typed in by hand.
    goal_weight_kg: float | None = Field(default=None, ge=30, le=300)
    weight_unit: Literal["kg", "lb"] = "kg"
    reminders_enabled: bool = False


class SettingsOut(SettingsIn):
    goal_set_by: str | None = None


class WeightIn(BaseModel):
    weight_kg: float = Field(ge=30, le=300)


class DailyTotal(BaseModel):
    date: str
    total_calories: float


class WeightOut(BaseModel):
    logged_on: str
    weight_kg: float


class CheckinIn(BaseModel):
    checked_on: str = Field(description="YYYY-MM-DD")
    weight_kg: float | None = Field(default=None, ge=30, le=300)


class PhotoUploadIn(BaseModel):
    pose: Literal["front", "side", "back"]


class PhotoRecordIn(BaseModel):
    pose: Literal["front", "side", "back"]
    path: str


class PhotoOut(BaseModel):
    id: int
    pose: Literal["front", "side", "back"]
    url: str


class CheckinOut(BaseModel):
    id: int
    checked_on: str
    weight_kg: float | None = None
    photos: list[PhotoOut] = []


class CheckinList(BaseModel):
    checkins: list[CheckinOut]
    next_due_on: str
    due: bool


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=512)
    auth: str = Field(min_length=1, max_length=512)


class PushSubscriptionIn(BaseModel):
    endpoint: HttpUrl
    keys: PushKeys

    @field_validator("endpoint")
    @classmethod
    def _https_only(cls, v):
        if v.scheme != "https":
            raise ValueError("endpoint must be https")
        if len(str(v)) > 2048:
            raise ValueError("endpoint too long")
        return v


class PushEndpointIn(BaseModel):
    endpoint: HttpUrl


# ---- workout routines ----

class RoutineIn(BaseModel):
    days_per_week: int = Field(ge=2, le=6)
    level: Literal["beginner", "intermediate", "advanced"]
    equipment: Literal["none", "dumbbells", "gym"]
    session_min: Literal[20, 30, 45, 60]


class RoutineItemOut(BaseModel):
    video_id: int
    youtube_id: str
    title: str
    channel: str
    category: str
    sets: int
    reps: int | None
    seconds: int | None
    rest_sec: int
    warm_up: bool = False
    available: bool


class RoutineDayOut(BaseModel):
    index: int
    type: str
    title: str
    why: str
    est_min: int
    items: list[RoutineItemOut]


class RoutineOut(BaseModel):
    id: int
    created_at: str
    days_per_week: int
    level: str
    equipment: str
    session_min: int
    goal: str
    source: str
    note: str | None
    days: list[RoutineDayOut]


class DoneOut(BaseModel):
    day_index: int
    done_on: str


class ActiveRoutineOut(BaseModel):
    routine: RoutineOut | None
    done: list[DoneOut]
    week_start: str | None


# ---- meal advice ----

class AdviceItem(BaseModel):
    """A food as shown on the result screen. Items added by hand have no confidence."""
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def _one_clean_line(cls, v: str) -> str:
        # Names go into the AI prompt: no line breaks or control characters that could pose as rules.
        v = re.sub(r"\s+", " ", v)
        v = "".join(c for c in v if not unicodedata.category(c).startswith("C")).strip()
        if not v:
            raise ValueError("name is empty")
        return v
    calories: float = Field(ge=0, le=5000)
    protein_g: float = Field(default=0, ge=0, le=500)
    carbs_g: float = Field(default=0, ge=0, le=1000)
    fat_g: float = Field(default=0, ge=0, le=500)


class AdviceIn(BaseModel):
    items: list[AdviceItem] = Field(min_length=1, max_length=20)
    eaten: bool
    date: str


class AdviceOut(BaseModel):
    text: str
    verdict: str
    source: str
