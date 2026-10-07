"""Inputs and outputs of the coach's read-only tools.

Inputs validate the model's arguments. user_id is never one of them: Formiq
sets it from the coach request. Outputs hold only the fields the coach needs,
never ORM objects, internal ids beyond the resource's own, or audit timestamps.
"""

from datetime import date, datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from app.schemas.exercise import CatalogId, Difficulty, MovementPattern, MuscleRole
from app.schemas.workout_plan import PositiveInteger, WorkoutPlanStatus
from app.schemas.workout_session import WorkoutSessionStatus


class ToolInput(BaseModel):
    # an argument the tool does not declare is a mistake, not something to ignore
    model_config = ConfigDict(extra="forbid")


class UserScopedInput(ToolInput):
    # set by Formiq from the coach request, never by the model
    user_id: PositiveInteger


class GetUserProfileInput(UserScopedInput):
    pass


class GetWorkoutPlanInput(UserScopedInput):
    plan_id: PositiveInteger


class GetWorkoutSessionInput(UserScopedInput):
    session_id: PositiveInteger


class GetExerciseInput(ToolInput):
    exercise_id: CatalogId


class SearchExercisesInput(ToolInput):
    """Catalog filters; an exercise must match all of those given."""

    equipment_id: CatalogId | None = None
    movement_pattern: MovementPattern | None = None
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def require_a_filter(self) -> Self:
        # without a filter the search would return the whole catalog
        if self.model_dump(exclude_none=True) == {}:
            raise ValueError(
                "at least one of equipment_id, movement_pattern, difficulty is required"
            )
        return self


class ProfileOutput(BaseModel):
    """The fitness fields of the profile; the user's name is left out."""

    model_config = ConfigDict(from_attributes=True)

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


class UserProfileOutput(BaseModel):
    user_id: int
    profile: ProfileOutput


class PlanExerciseOutput(BaseModel):
    """An exercise as prescribed in the plan, not as performed."""

    exercise_id: int
    exercise_name: str | None
    exercise_order: int
    sets: int
    reps: int
    weight_kg: float | None
    rest_seconds: int | None
    notes: str | None


class WorkoutPlanOutput(BaseModel):
    plan_id: int
    name: str
    status: WorkoutPlanStatus
    scheduled_date: date | None
    # ordered by exercise_order
    exercises: list[PlanExerciseOutput]
    # true when exercises beyond the tool's limit were left out
    truncated: bool


class WorkoutSetOutput(BaseModel):
    """A set as performed."""

    set_number: int
    reps: int
    weight_kg: float | None
    rpe: float | None
    completed: bool


class SessionExerciseOutput(BaseModel):
    exercise_id: int
    exercise_name: str | None
    exercise_order: int
    # ordered by set_number
    sets: list[WorkoutSetOutput]


class WorkoutSessionOutput(BaseModel):
    session_id: int
    workout_plan_id: int | None
    status: WorkoutSessionStatus
    started_at: datetime
    completed_at: datetime | None
    notes: str | None
    # ordered by exercise_order
    exercises: list[SessionExerciseOutput]
    # true when exercises or sets beyond the tool's limits were left out
    truncated: bool


class MuscleOutput(BaseModel):
    name: str
    role: MuscleRole


class ExerciseOutput(BaseModel):
    exercise_id: int
    name: str
    description: str | None
    difficulty: Difficulty
    movement_pattern: MovementPattern
    # primary muscles first
    muscles: list[MuscleOutput]
    # equipment names; empty when no equipment is needed
    equipment: list[str]
    is_active: bool


class ExerciseSummaryOutput(BaseModel):
    exercise_id: int
    name: str
    difficulty: Difficulty
    movement_pattern: MovementPattern
    # muscle names, primary muscles first
    muscles: list[str]
    equipment: list[str]


class SearchExercisesOutput(BaseModel):
    # ordered by name
    exercises: list[ExerciseSummaryOutput]
    count: int
