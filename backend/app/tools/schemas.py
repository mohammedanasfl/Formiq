"""Inputs and outputs of the coach's read-only tools.

Inputs validate the model's arguments. user_id is never one of them: Formiq
sets it from the coach request. Outputs hold only the fields the coach needs,
never ORM objects, internal ids beyond the resource's own, or audit timestamps.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.exercise import Difficulty, MovementPattern, MuscleRole
from app.schemas.workout_plan import MAX_INTEGER, PositiveInteger, WorkoutPlanStatus
from app.schemas.workout_session import WorkoutSessionStatus
from app.tools.limits import (
    MAX_PROPOSED_EXERCISES,
    MAX_PROPOSED_REPS,
    MAX_PROPOSED_REST_SECONDS,
    MAX_PROPOSED_SETS,
)

# A resource id from the model, in its one canonical form (as
# app.agent.policy.is_canonical_id): a positive JSON integer within the
# columns' range. Strict, so true, 7.0 and strings such as "7", "+7", "7.0" or
# "1_0" are rejected, never coerced into an id.
ResourceId = Annotated[int, Field(strict=True, ge=1, le=MAX_INTEGER)]


class ToolInput(BaseModel):
    # an argument the tool does not declare is a mistake, not something to ignore
    model_config = ConfigDict(extra="forbid")


class UserScopedInput(ToolInput):
    # set by Formiq from the coach request, never by the model
    user_id: PositiveInteger


class GetUserProfileInput(UserScopedInput):
    pass


class GetWorkoutPlanInput(UserScopedInput):
    plan_id: ResourceId


class GetWorkoutSessionInput(UserScopedInput):
    session_id: ResourceId


class GetCurrentWorkoutPlanInput(UserScopedInput):
    pass


class GetLatestWorkoutSessionInput(UserScopedInput):
    pass


# A proposed plan's prescription, within Formiq's coaching bounds; strict, like
# ResourceId, so 3.0, true or "3" is never coerced into a count.
ProposedSets = Annotated[int, Field(strict=True, ge=1, le=MAX_PROPOSED_SETS)]
ProposedReps = Annotated[int, Field(strict=True, ge=1, le=MAX_PROPOSED_REPS)]
ProposedRest = Annotated[int, Field(strict=True, ge=0, le=MAX_PROPOSED_REST_SECONDS)]
AvailableMinutes = Annotated[int, Field(strict=True, ge=10, le=180)]
PlanName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
ShortNote = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EquipmentName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
]


class ProposedExerciseInput(ToolInput):
    """An exercise of a proposed plan: a catalog exercise and its prescription.
    No weight: the coach does not prescribe loads it cannot know."""

    exercise_id: ResourceId
    sets: ProposedSets
    reps: ProposedReps
    rest_seconds: ProposedRest | None = None
    notes: ShortNote | None = None


class ProposeWorkoutPlanInput(UserScopedInput):
    name: PlanName
    # today when not given
    scheduled_date: date | None = None
    exercises: Annotated[
        list[ProposedExerciseInput], Field(min_length=1, max_length=MAX_PROPOSED_EXERCISES)
    ]
    # the user's own constraints, which the proposal must fit
    max_minutes: AvailableMinutes | None = None
    unavailable_equipment: Annotated[list[EquipmentName], Field(max_length=10)] = []


class GetExerciseInput(ToolInput):
    exercise_id: ResourceId


class SearchExercisesInput(ToolInput):
    """Catalog filters; an exercise must match all of those given."""

    equipment_id: ResourceId | None = None
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
    """The user's name and the fitness fields of the profile. Never contact
    details: the user's email and phone are in the users table, which the
    coach's tools do not read."""

    model_config = ConfigDict(from_attributes=True)

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


class CurrentWorkoutPlanOutput(WorkoutPlanOutput):
    """The current plan, placed relative to today (Formiq's date, in UTC), so
    the model does not work out dates itself."""

    today: date
    # scheduled_date - today, in days: 0 today, 1 tomorrow, -1 yesterday
    days_from_today: int | None


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


class LatestWorkoutSessionOutput(WorkoutSessionOutput):
    """The last workout, placed relative to today (Formiq's date, in UTC)."""

    today: date
    # today - the day it was completed (or started), in days: 0 today, 1 yesterday
    days_ago: int


class ProposedExerciseOutput(BaseModel):
    exercise_order: int
    exercise_id: int
    exercise_name: str
    # what the exercise needs, from the catalog; empty when nothing
    equipment: list[str]
    sets: int
    reps: int
    rest_seconds: int | None
    notes: str | None


class ProposedWorkoutPlanOutput(BaseModel):
    """A workout plan Formiq has proposed to the user. Not saved: only the
    user's own approval in Formiq saves it."""

    status: Literal["awaiting_user_approval"] = "awaiting_user_approval"
    name: str
    scheduled_date: date
    days_from_today: int
    # ordered by exercise_order
    exercises: list[ProposedExerciseOutput]
    # Formiq's estimate: each set and its rest
    estimated_minutes: int
    expires_at: datetime


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
