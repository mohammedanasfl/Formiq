from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.exercise import CatalogId
from app.schemas.workout_plan import PositiveInteger, Text, Weight

# Rate of perceived exertion: 1 (very easy) to 10 (maximal effort). Half points
# such as 7.5 are allowed; infinity and NaN are not.
Rpe = Annotated[float, Field(ge=1, le=10, allow_inf_nan=False)]


class WorkoutSessionStatus(StrEnum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkoutSetCreate(BaseModel):
    """A set actually performed. completed is false for a skipped or incomplete set."""

    set_number: PositiveInteger
    reps: PositiveInteger
    weight_kg: Weight | None = None
    rpe: Rpe | None = None
    completed: bool = True
    notes: Text | None = None


class WorkoutSetUpdate(BaseModel):
    set_number: PositiveInteger | None = None
    reps: PositiveInteger | None = None
    weight_kg: Weight | None = None
    rpe: Rpe | None = None
    completed: bool | None = None
    notes: Text | None = None


class WorkoutSetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workout_session_exercise_id: int
    set_number: int
    reps: int
    weight_kg: float | None
    rpe: float | None
    completed: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


class WorkoutSessionExerciseCreate(BaseModel):
    """An exercise performed in a session. plan_exercise_id optionally links the
    planned exercise it was done for, which may be a different exercise."""

    exercise_id: CatalogId
    exercise_order: PositiveInteger
    plan_exercise_id: PositiveInteger | None = None
    notes: Text | None = None


class WorkoutSessionExerciseUpdate(BaseModel):
    exercise_id: CatalogId | None = None
    exercise_order: PositiveInteger | None = None
    plan_exercise_id: PositiveInteger | None = None
    notes: Text | None = None


class WorkoutSessionExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workout_session_id: int
    plan_exercise_id: int | None
    exercise_id: int
    exercise_order: int
    notes: str | None
    # ordered by set_number
    sets: list[WorkoutSetResponse]
    created_at: datetime
    updated_at: datetime


class WorkoutSessionCreate(BaseModel):
    """Starts a session: from one of the user's workout plans, or a manual
    workout without one. It starts IN_PROGRESS, at the current time."""

    workout_plan_id: PositiveInteger | None = None
    notes: Text | None = None


class WorkoutSessionUpdate(BaseModel):
    """The session fields to change. The plan and timestamps cannot be changed;
    its exercises and sets are changed through their own routes."""

    status: WorkoutSessionStatus | None = None
    notes: Text | None = None


class WorkoutSessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    workout_plan_id: int | None
    status: WorkoutSessionStatus
    started_at: datetime
    completed_at: datetime | None
    notes: str | None
    # ordered by exercise_order
    exercises: list[WorkoutSessionExerciseResponse]
    created_at: datetime
    updated_at: datetime


class WorkoutSessionFilters(BaseModel):
    """Filters for listing a user's workout sessions."""

    status: WorkoutSessionStatus | None = None
