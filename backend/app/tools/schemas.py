"""Inputs and outputs of the coach's read-only tools.

Inputs validate the model's arguments. user_id is never one of them: Formiq
sets it from the coach request. Outputs hold only the fields the coach needs,
never ORM objects, internal ids beyond the resource's own, or audit timestamps.
"""

from datetime import date, datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from app.schemas.coach import ProposalCoverage, ProposalRevision, RevisionKind, SessionFocus
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
    # another of the user's plans, to say what differs between the two
    compare_with_plan_id: ResourceId | None = None


class ListWorkoutPlansInput(UserScopedInput):
    # only the plans in this status; every plan when not given
    status: WorkoutPlanStatus | None = None


class GetPendingProposalInput(UserScopedInput):
    pass


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
    # what the main workout trains, which it must fulfil (app.tools.completeness)
    focus: SessionFocus = SessionFocus.FULL_BODY
    warm_up: SectionActivities
    # the main workout
    exercises: Annotated[
        list[ProposedExerciseInput], Field(min_length=1, max_length=MAX_PROPOSED_EXERCISES)
    ]
    cool_down: SectionActivities
    # the user's own constraints, which the proposal must fit
    max_minutes: AvailableMinutes | None = None
    # the equipment the user has, when they said, as search_exercises takes it
    # ([] for none at all): every exercise must need nothing else
    available_equipment: Annotated[
        list[EquipmentName], Field(max_length=MAX_SEARCH_EQUIPMENT)
    ] | None = None
    unavailable_equipment: Annotated[
        list[EquipmentName], Field(max_length=MAX_UNAVAILABLE_EQUIPMENT)
    ] = []
    # the user's saved plan it revises, when they asked to change, rewrite or
    # replace one, and how: approving it then cancels that plan
    revises_plan_id: ResourceId | None = None
    revision: RevisionKind | None = None

    @model_validator(mode="after")
    def revision_of_a_plan(self) -> Self:
        if (self.revises_plan_id is None) != (self.revision is None):
            raise ValueError(
                "revises_plan_id and revision go together: give both to revise a saved plan, "
                "or neither for a new workout"
            )
        return self


class GetExerciseInput(ToolInput):
    exercise_id: ResourceId


MuscleName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class SearchExercisesInput(ToolInput):
    """Catalog filters; an exercise must match all of those given."""

    use: WorkoutSection | None = None
    # a muscle group the exercise trains, by its Formiq name
    muscle: MuscleName | None = None
    # the equipment the user has, by name: the exercise needs nothing else
    # ([] for none at all; a name such as "body weight" says the same)
    available_equipment: Annotated[
        list[EquipmentName], Field(max_length=MAX_SEARCH_EQUIPMENT)
    ] | None = None
    # One piece the exercise must use, by the catalog's name or a common one for
    # it (read by app.tools.equipment, as available_equipment is). Never an id:
    # no tool gives the model an equipment id, so none could be grounded.
    equipment: EquipmentName | None = None
    movement_pattern: MovementPattern | None = None
    difficulty: Difficulty | None = None

    @model_validator(mode="after")
    def require_a_filter(self) -> Self:
        # without a filter the search would return the whole catalog
        if self.model_dump(exclude_none=True) == {}:
            raise ValueError(
                "at least one of use, muscle, available_equipment, equipment, "
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


class ExerciseChangeOutput(BaseModel):
    """An exercise one workout has and the other has not, or has with another
    prescription, as "3 sets of 10 reps, 60 s rest"."""

    section: PlanSection
    exercise_name: str
    before: str | None
    after: str | None


class WorkoutChangesOutput(BaseModel):
    """What differs between two workouts, worked out by Formiq from what each
    prescribes, by section and exercise: nothing else differs."""

    # the saved plan the workout is compared with
    compared_with_plan_id: int
    compared_with_plan_name: str
    # the exercises only the workout has, those only the plan has, and those
    # both have with another prescription; in section order
    added: list[ExerciseChangeOutput]
    removed: list[ExerciseChangeOutput]
    changed: list[ExerciseChangeOutput]
    # the exercises both have, prescribed alike, by name
    unchanged: list[str]
    name_changed: bool
    scheduled_date_changed: bool
    # true when the two prescribe the same workout
    identical: bool


class WorkoutPlanOutput(BaseModel):
    plan_id: int
    name: str
    status: WorkoutPlanStatus
    scheduled_date: date | None
    # ordered by exercise_order
    exercises: list[PlanExerciseOutput]
    # true when exercises beyond the tool's limit were left out
    truncated: bool
    # with compare_with_plan_id: how this plan differs from that one
    changes: WorkoutChangesOutput | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class PlanSummaryOutput(BaseModel):
    """One of the user's saved plans, in short."""

    plan_id: int
    name: str
    status: WorkoutPlanStatus
    scheduled_date: date | None
    # scheduled_date - today, in days: 0 today, 1 tomorrow, -1 yesterday
    days_from_today: int | None
    # the first main exercises' names (at most 8), in order, and how many
    # exercises it has in all
    main_exercises: list[str]
    exercise_count: int
    # whether it is the plan get_current_workout_plan returns
    is_current: bool


class WorkoutPlanListOutput(BaseModel):
    """The user's saved plans: PLANNED first, the next one first, then the
    others, the latest scheduled first."""

    today: date
    plans: list[PlanSummaryOutput]
    # how many are returned, and how many match in all
    count: int
    total: int
    # how many of them are PLANNED, whether or not they were all returned
    planned: int
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
    # how many of its logged sets are marked completed: an exercise with none
    # was not done, whatever the plan says
    completed_sets: int


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
    # whether the main workout fulfils its focus, and what is missing when not
    coverage: ProposalCoverage
    expires_at: datetime
    # the saved plan its approval would replace; left out for a new workout
    revision: ProposalRevision | None = Field(default=None, exclude_if=lambda value: value is None)


class PendingProposalOutput(BaseModel):
    """The workout Formiq proposed to the user earlier, still awaiting their
    approval, from Formiq's records: not saved, and unchanged since it was
    shown. Only the user's approval in Formiq saves it."""

    status: Literal["awaiting_user_approval"] = "awaiting_user_approval"
    name: str
    scheduled_date: date
    days_from_today: int
    # how long it still waits for the user's approval
    expires_in_minutes: int
    # ordered by exercise_order: the warm-up, the main workout, the cool-down
    exercises: list[ProposedExerciseOutput]
    warm_up_minutes: int
    main_minutes: int
    cool_down_minutes: int
    estimated_minutes: int
    # as when it was proposed; null for a proposal made before Formiq recorded it
    coverage: ProposalCoverage | None
    # the saved plan its approval replaces; null for a new workout
    revision: ProposalRevision | None
    # whether that plan is still as it was when proposed: if not, approving
    # the proposal fails, and a new one is needed
    replaced_plan_unchanged: bool | None
    # how it differs from the plan it revises, or else from the current plan
    # (null when there is neither)
    changes: WorkoutChangesOutput | None
    # other proposals of the user's still awaiting approval, made before it
    earlier_proposals_awaiting_approval: int


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
    # In a warm-up or cool-down search, once the request's searches returned
    # main exercises: the ids of those this activity may go with in a proposal
    # ("any" for easy CARDIO), as propose_workout_plan checks it. Left out
    # otherwise.
    suits_main: list[int] | Literal["any"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )


class OtherUseExerciseOutput(BaseModel):
    """An exercise that matches a search's other filters but that Formiq does not
    use for the section searched. It has no id: it is not a choice for that
    section, and no proposal may be built from it."""

    name: str
    # the sections Formiq does use it for; empty when it uses it for none
    uses: list[WorkoutSection]
    equipment: list[str]


class OtherUseMatchesOutput(BaseModel):
    """What a search for a section that found nothing leaves out only because of
    that section: so that "nothing found" is not said of the catalog as a whole."""

    # how many such exercises there are, and a few of them (at most
    # MAX_OTHER_USE_MATCHES, the most relevant first)
    total: int
    exercises: list[OtherUseExerciseOutput]


class SearchExercisesOutput(BaseModel):
    # the most relevant first (app.tools.formiq_tools.most_relevant)
    exercises: list[ExerciseSummaryOutput]
    # how many are returned, and how many match in all
    count: int
    total_matches: int
    # for a workout (a search by use): the equipment the user said they lack,
    # which no exercise returned needs; left out when they said nothing
    excluded_equipment: list[str] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    # For a search by use that found nothing: the exercises that match every other
    # filter but are used for another section only (or for none). They are not
    # results for this use; they say that the catalog does have such exercises.
    # Left out when the search found something, or nothing matched without the use.
    matches_for_other_uses: OtherUseMatchesOutput | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
