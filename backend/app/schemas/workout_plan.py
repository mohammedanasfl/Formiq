from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.exercise import CatalogId, WorkoutSection

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


# The part of the workout a planned exercise belongs to: the warm-up, the main
# workout or the cool-down, the same sections a catalog exercise's uses name.
PlanSection = WorkoutSection


def check_set_target(reps: int | None, duration_seconds: int | None) -> None:
    """Each set has one target: reps, or a duration (a timed activity, such as
    an easy walk or a stretch held)."""
    if (reps is None) == (duration_seconds is None):
        raise ValueError("give each set one target: reps or duration_seconds, not both")


class WorkoutPlanExerciseCreate(BaseModel):
    """An exercise to prescribe in a plan: target values, not performed ones."""

    exercise_id: CatalogId
    exercise_order: PositiveInteger
    section: PlanSection = PlanSection.MAIN_WORKOUT
    sets: PositiveInteger
    reps: PositiveInteger | None = None
    duration_seconds: PositiveInteger | None = None
    weight_kg: Weight | None = None
    rest_seconds: Seconds | None = None
    notes: Text | None = None

    @model_validator(mode="after")
    def check_target(self) -> Self:
        check_set_target(self.reps, self.duration_seconds)
        return self


class WorkoutPlanExerciseUpdate(BaseModel):
    """The fields to change. The result must still have one target per set
    (checked by the service, which sees the stored values)."""

    exercise_id: CatalogId | None = None
    exercise_order: PositiveInteger | None = None
    section: PlanSection | None = None
    sets: PositiveInteger | None = None
    reps: PositiveInteger | None = None
    duration_seconds: PositiveInteger | None = None
    weight_kg: Weight | None = None
    rest_seconds: Seconds | None = None
    notes: Text | None = None


class PlannedExerciseDetailsResponse(BaseModel):
    """What the catalog says about a planned exercise, from Formiq's database,
    so a saved plan can be shown and followed without asking the coach again.
    Missing content is never made up: an exercise without instructions has
    none here (an empty list), and one without a description has null."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    # Formiq's own short description; null for an imported exercise, whose
    # upstream record has none
    description: str | None
    # the upstream record's steps, in order and unchanged; empty for Formiq's
    # own exercises and for an imported one whose record has none
    instructions: list[str]


class WorkoutPlanExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workout_plan_id: int
    exercise_id: int
    # the catalog exercise exercise_id names, as the catalog has it now
    exercise: PlannedExerciseDetailsResponse
    exercise_order: int
    section: PlanSection
    sets: int
    # one of them per set: reps, or seconds for a timed activity
    reps: int | None
    duration_seconds: int | None
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
    # ordered by exercise_order; each in its section (warm-up, main, cool-down)
    exercises: list[WorkoutPlanExerciseResponse]
    created_at: datetime
    updated_at: datetime


class WorkoutPlanFilters(BaseModel):
    """Filters for listing a user's workout plans. A plan must match all of them."""

    status: WorkoutPlanStatus | None = None
    scheduled_date: date | None = None
