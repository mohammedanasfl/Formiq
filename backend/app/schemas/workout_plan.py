from datetime import date, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.exercise import CatalogId

# The integer columns are PostgreSQL integers, so larger values would fail in
# the database. This is the column's limit, not a training limit.
MAX_INTEGER = 2_147_483_647

PlanName = Annotated[str, StringConstraints(min_length=1, max_length=150)]
Text = Annotated[str, StringConstraints(min_length=1)]
PositiveInteger = Annotated[int, Field(ge=1, le=MAX_INTEGER)]
Seconds = Annotated[int, Field(ge=0, le=MAX_INTEGER)]
# infinity and NaN are not weights
Weight = Annotated[float, Field(gt=0, allow_inf_nan=False)]


class WorkoutPlanStatus(StrEnum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    CANCELLED = "CANCELLED"


class WorkoutPlanExerciseCreate(BaseModel):
    """An exercise to prescribe in a plan: target values, not performed ones."""

    exercise_id: CatalogId
    exercise_order: PositiveInteger
    sets: PositiveInteger
    reps: PositiveInteger
    weight_kg: Weight | None = None
    rest_seconds: Seconds | None = None
    notes: Text | None = None


class WorkoutPlanExerciseUpdate(BaseModel):
    exercise_id: CatalogId | None = None
    exercise_order: PositiveInteger | None = None
    sets: PositiveInteger | None = None
    reps: PositiveInteger | None = None
    weight_kg: Weight | None = None
    rest_seconds: Seconds | None = None
    notes: Text | None = None


class WorkoutPlanExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workout_plan_id: int
    exercise_id: int
    exercise_order: int
    sets: int
    reps: int
    weight_kg: float | None
    rest_seconds: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class WorkoutPlanCreate(BaseModel):
    name: PlanName
    description: Text | None = None
    status: WorkoutPlanStatus = WorkoutPlanStatus.DRAFT
    scheduled_date: date | None = None
    # optional: exercises can also be added after the plan is created
    exercises: list[WorkoutPlanExerciseCreate] = []


class WorkoutPlanUpdate(BaseModel):
    """The plan fields to change. Its exercises are changed through their own routes."""

    name: PlanName | None = None
    description: Text | None = None
    status: WorkoutPlanStatus | None = None
    scheduled_date: date | None = None


class WorkoutPlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    description: str | None
    status: WorkoutPlanStatus
    scheduled_date: date | None
    # ordered by exercise_order
    exercises: list[WorkoutPlanExerciseResponse]
    created_at: datetime
    updated_at: datetime


class WorkoutPlanFilters(BaseModel):
    """Filters for listing a user's workout plans. A plan must match all of them."""

    status: WorkoutPlanStatus | None = None
    scheduled_date: date | None = None
