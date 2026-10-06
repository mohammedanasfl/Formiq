from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    StringConstraints,
)

# Text limited to the length of the matching user_profiles column.
Name = Annotated[str, StringConstraints(min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=50)]


class UserProfileCreate(BaseModel):
    first_name: Name
    last_name: Name | None = None
    age: PositiveInt
    height_cm: PositiveFloat
    weight_kg: PositiveFloat
    gender: ShortText
    fitness_experience: ShortText
    goal: ShortText
    target_weight_kg: PositiveFloat | None = None
    goal_period_weeks: PositiveInt | None = None
    training_frequency_per_week: NonNegativeInt
    training_location: ShortText
    activity_level: ShortText
    sleep_hours: NonNegativeFloat
    dietary_preference: ShortText | None = None


class UserProfileUpdate(BaseModel):
    first_name: Name | None = None
    last_name: Name | None = None
    age: PositiveInt | None = None
    height_cm: PositiveFloat | None = None
    weight_kg: PositiveFloat | None = None
    gender: ShortText | None = None
    fitness_experience: ShortText | None = None
    goal: ShortText | None = None
    target_weight_kg: PositiveFloat | None = None
    goal_period_weeks: PositiveInt | None = None
    training_frequency_per_week: NonNegativeInt | None = None
    training_location: ShortText | None = None
    activity_level: ShortText | None = None
    sleep_hours: NonNegativeFloat | None = None
    dietary_preference: ShortText | None = None


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str | None
    age: int
    height_cm: float
    weight_kg: float
    gender: str
    fitness_experience: str
    goal: str
    target_weight_kg: float | None
    goal_period_weeks: int | None
    training_frequency_per_week: int
    training_location: str
    activity_level: str
    sleep_hours: float
    dietary_preference: str | None
    created_at: datetime
    updated_at: datetime
