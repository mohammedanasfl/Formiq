"""Inputs and outputs of the coach's read-only tools.

Inputs validate the model's arguments. user_id is never one of them: Formiq
sets it from the coach request. Outputs hold only the fields the coach needs,
never ORM objects, internal ids beyond the resource's own, or audit timestamps.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.exercise import Difficulty, MovementPattern, MuscleRole, WorkoutSection
from app.schemas.workout_plan import (
    MAX_INTEGER,
    PlanSection,
    PositiveInteger,
    WorkoutPlanStatus,
    check_set_target,
)
from app.schemas.workout_session import WorkoutSessionStatus
from app.tools.limits import (
    MAX_ACTIVITY_REPS,
    MAX_ACTIVITY_SECONDS,
    MAX_ACTIVITY_SETS,
    MAX_PROPOSED_EXERCISES,
    MAX_PROPOSED_REPS,
    MAX_PROPOSED_REST_SECONDS,
    MAX_PROPOSED_SETS,
    MAX_SEARCH_EQUIPMENT,
    MAX_SECTION_ACTIVITIES,
    MAX_UNAVAILABLE_EQUIPMENT,
    MIN_ACTIVITY_SECONDS,
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
    """An exercise of a proposed plan's main workout: a catalog exercise and its
    prescription. No weight: the coach does not prescribe loads it cannot know."""

    exercise_id: ResourceId
    sets: ProposedSets
    reps: ProposedReps
    rest_seconds: ProposedRest | None = None
    notes: ShortNote | None = None


# A warm-up or cool-down activity's prescription: light, and strict likewise.
ActivitySets = Annotated[int, Field(strict=True, ge=1, le=MAX_ACTIVITY_SETS)]
ActivityReps = Annotated[int, Field(strict=True, ge=1, le=MAX_ACTIVITY_REPS)]
ActivitySeconds = Annotated[
    int, Field(strict=True, ge=MIN_ACTIVITY_SECONDS, le=MAX_ACTIVITY_SECONDS)
]


class ProposedActivityInput(ToolInput):
    """A warm-up or cool-down activity of a proposed plan: a light catalog
    exercise, done for reps or for a time (one of them), with no rest between
    activities and no weight."""

    exercise_id: ResourceId
    sets: ActivitySets
    reps: ActivityReps | None = None
    duration_seconds: ActivitySeconds | None = None
    notes: ShortNote | None = None

    @model_validator(mode="after")
    def one_target(self) -> Self:
        check_set_target(self.reps, self.duration_seconds)
        return self


SectionActivities = Annotated[
    list[ProposedActivityInput], Field(min_length=1, max_length=MAX_SECTION_ACTIVITIES)
]


class ProposeWorkoutPlanInput(UserScopedInput):
    """A whole workout, in its three sections, in the order they are done."""

    name: PlanName
    # today when not given
    scheduled_date: date | None = None
    warm_up: SectionActivities
    # the main workout
    exercises: Annotated[
        list[ProposedExerciseInput], Field(min_length=1, max_length=MAX_PROPOSED_EXERCISES)
    ]
    cool_down: SectionActivities
    # the user's own constraints, which the proposal must fit
    max_minutes: AvailableMinutes | None = None
    unavailable_equipment: Annotated[
        list[EquipmentName], Field(max_length=MAX_UNAVAILABLE_EQUIPMENT)
    ] = []


class GetExerciseInput(ToolInput):
    exercise_id: ResourceId


MuscleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SearchExercisesInput(ToolInput):
    """Catalog filters; an exercise must match all of those given."""

    use: WorkoutSection | None = None
    # a muscle group the exercise trains, by its Formiq name
    muscle: MuscleName | None = None
    # the equipment the user has, by name: the exercise needs nothing else
    # ([] for none at all)
    available_equipment: Annotated[
        list[EquipmentName], Field(max_length=MAX_SEARCH_EQUIPMENT)
    ] | None = None
    equipment_id: ResourceId | None = None
    movement_pattern: MovementPattern | None = None
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def require_a_filter(self) -> Self:
        # without a filter the search would return the whole catalog
        if self.model_dump(exclude_none=True) == {}:
            raise ValueError(
                "at least one of use, muscle, available_equipment, equipment_id, "
                "movement_pattern, difficulty is required"
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
    # the warm-up, the main workout or the cool-down
    section: PlanSection
    sets: int
    # each set's target: reps, or a duration in seconds
    reps: int | None
    duration_seconds: int | None
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
    section: PlanSection
    exercise_id: int
    exercise_name: str
    # what the exercise needs, from the catalog; empty when nothing
    equipment: list[str]
    sets: int
    # each set's target: reps, or a duration in seconds (warm-up and cool-down)
    reps: int | None
    duration_seconds: int | None
    rest_seconds: int | None
    notes: str | None


class ProposedWorkoutPlanOutput(BaseModel):
    """A workout plan Formiq has proposed to the user. Not saved: only the
    user's own approval in Formiq saves it."""

    status: Literal["awaiting_user_approval"] = "awaiting_user_approval"
    name: str
    scheduled_date: date
    days_from_today: int
    # ordered by exercise_order: the warm-up, the main workout, the cool-down
    exercises: list[ProposedExerciseOutput]
    # Formiq's estimate of each section (each set, and its rest), and their sum
    warm_up_minutes: int
    main_minutes: int
    cool_down_minutes: int
    estimated_minutes: int
    expires_at: datetime


class MuscleOutput(BaseModel):
    name: str
    role: MuscleRole


class ExerciseOutput(BaseModel):
    exercise_id: int
    name: str
    description: str | None
    # the steps, in order; at most MAX_INSTRUCTION_STEPS
    instructions: list[str]
    difficulty: Difficulty
    # null when Formiq has not classified it
    movement_pattern: MovementPattern | None
    # the upstream dataset's category, for an imported exercise
    category: str | None
    # the workout sections Formiq uses it for
    uses: list[WorkoutSection]
    # primary muscles first
    muscles: list[MuscleOutput]
    # equipment names; empty when no equipment is needed
    equipment: list[str]
    is_active: bool
    # true when instruction steps beyond the limit were left out
    truncated: bool


class ExerciseSummaryOutput(BaseModel):
    exercise_id: int
    name: str
    difficulty: Difficulty
    movement_pattern: MovementPattern | None
    uses: list[WorkoutSection]
    # muscle names, primary muscles first
    muscles: list[str]
    equipment: list[str]


class SearchExercisesOutput(BaseModel):
    # ordered by name
    exercises: list[ExerciseSummaryOutput]
    # how many are returned, and how many match in all
    count: int
    total_matches: int
