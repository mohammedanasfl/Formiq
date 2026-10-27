from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.schemas.timezone import TIMEZONE_PATTERN, zone_of
from app.schemas.workout_plan import MAX_INTEGER, PlanSection

# Surrounding whitespace is dropped, and a blank message is rejected. The limit
# keeps one message, and the model request it becomes, a reasonable size.
CoachMessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]


# Earlier turns one request may carry: the coach keeps only the most recent
# (app.agent.context), so more would only make the request larger.
MAX_HISTORY_TURNS = 50
# as long as a coach reply may be (app.agent.policy.MAX_REPLY_LENGTH); the coach
# shortens long turns
MAX_HISTORY_TEXT_LENGTH = 8000


class CoachHistoryTurn(BaseModel):
    """An earlier turn of the conversation: what the user wrote, or the coach's
    reply. Formiq stores no conversation, so the client sends the turns it
    wants the coach to see; they are context, not Formiq data."""

    role: Literal["user", "coach"]
    text: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=MAX_HISTORY_TEXT_LENGTH
        ),
    ]


class CoachMessageRequest(BaseModel):
    """A message to the coach from the signed-in user. The user is the access
    token's, never the body's: a body that names a user_id, or any other field
    not here, is rejected."""

    model_config = ConfigDict(extra="forbid")

    message: CoachMessageText
    # earlier turns, oldest first; the coach keeps the most recent ones
    history: list[CoachHistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    # The saved workout plan the user is changing, when they opened the coach
    # from it: theirs and PLANNED, checked before the model is asked anything,
    # and then the only plan this request's proposal may revise. Left out (or
    # null), the coach works out what the user means from the conversation.
    # Strict, as the coach's own ids are: "7" and 7.0 are not an id.
    workout_plan_id: Annotated[int, Field(strict=True, ge=1, le=MAX_INTEGER)] | None = None
    # The user's IANA time zone, as their device has it ("Asia/Kolkata"): "today", "tomorrow" and
    # the 14-day window are their local days in it (Phase 2.7, app.tools.coach_calendar). Left out
    # or null, they are UTC days, which the coach is told. Refused (422) when it is not a zone of the
    # time zone database: never guessed, never replaced by UTC without saying so.
    timezone: Annotated[str, StringConstraints(pattern=TIMEZONE_PATTERN)] | None = None

    @field_validator("timezone")
    @classmethod
    def a_known_time_zone(cls, value: str | None) -> str | None:
        if value is not None and zone_of(value) is None:
            raise ValueError("timezone must be an IANA time zone name such as Asia/Kolkata or UTC")
        return value


class SessionFocus(StrEnum):
    """What a proposed workout trains: the whole body, or one part of it
    (app.tools.completeness has what each requires)."""

    FULL_BODY = "FULL_BODY"
    UPPER_BODY = "UPPER_BODY"
    LOWER_BODY = "LOWER_BODY"
    PUSH = "PUSH"
    PULL = "PULL"
    CORE = "CORE"


class BodyRegion(StrEnum):
    """A part of the body a main exercise trains, from its primary muscles."""

    LOWER_BODY = "LOWER_BODY"
    UPPER_PUSH = "UPPER_PUSH"
    UPPER_PULL = "UPPER_PULL"
    CORE = "CORE"


class RevisionKind(StrEnum):
    """How a proposal revises one of the user's plans: the changes they asked
    for, keeping the rest (ADJUST), or a different workout for the same
    purpose (ALTERNATIVE)."""

    ADJUST = "ADJUST"
    ALTERNATIVE = "ALTERNATIVE"


class ProposalRevision(BaseModel):
    """The saved plan a proposal revises: approving the proposal saves it as a
    new plan and cancels that one, in one transaction."""

    replaces_plan_id: int
    replaces_plan_name: str
    kind: RevisionKind
    # the main exercises it keeps from that plan, by name: an ALTERNATIVE
    # keeps only those the catalog has no other suitable exercise for
    kept_exercises: list[str]


class ProposalRevisionResponse(ProposalRevision):
    """A revision as the API shows it: also how long the plan it replaces takes."""

    # Formiq's estimate, by the formula that gives a proposal's estimated_minutes
    # (a plan stores no length); null when the plan cannot be read as it was
    # proposed, so a client never compares with a length it was not given
    replaces_plan_estimated_minutes: int | None


class Prescription(BaseModel):
    """What a workout asks of one exercise."""

    sets: int
    # each set's target: reps, or a duration in seconds (one of them)
    reps: int | None
    duration_seconds: int | None
    rest_seconds: int | None
    # in kg: a saved plan may carry a weight, and a proposal carries it on unless
    # the user gave another or asked for none; null for none
    weight_kg: float | None
    # the same, as one line: "3 sets of 10 reps at 20 kg, 60 s rest"
    summary: str


class ExerciseChange(BaseModel):
    """An exercise one workout has and the other has not (the other side is
    null), or has with another prescription (both sides)."""

    section: PlanSection
    exercise_name: str
    before: Prescription | None
    after: Prescription | None


class ProposalChanges(BaseModel):
    """What differs between a proposal and the saved plan it replaces, worked
    out by Formiq from what each prescribes, by section and exercise: nothing
    else differs. The coach's own comparison (app.tools.comparison): the one
    the coach is held to when it describes a change."""

    # the saved plan the proposal is compared with, and the day it is scheduled
    # for (the proposal's own day is in the proposal)
    compared_with_plan_id: int
    compared_with_plan_name: str
    compared_with_scheduled_date: date | None
    # the exercises only the proposal has, those only the plan has, and those
    # both have with another prescription (its weight included); in section
    # order
    added: list[ExerciseChange]
    removed: list[ExerciseChange]
    changed: list[ExerciseChange]
    # the exercises both have, prescribed alike, by name
    unchanged: list[str]
    name_changed: bool
    scheduled_date_changed: bool
    # true when the two prescribe the same workout
    identical: bool


class CoverageLimitation(BaseModel):
    """Why a proposed workout falls short of its focus: Formiq's catalog has
    no exercise, or too few, that the user can do for it."""

    code: Literal["NO_SUITABLE_EXERCISE", "TOO_FEW_SUITABLE_EXERCISES"]
    # the region left untrained; null when the main workout is short of exercises
    region: BodyRegion | None
    message: str


class ProposalCoverage(BaseModel):
    """How completely a proposed workout's main exercises fulfil its focus.
    Formiq proposes an incomplete workout only when its catalog leaves no
    choice, and then says so here: complete is false and each limitation
    names what is missing."""

    complete: bool
    focus: SessionFocus
    # the regions the main exercises train, and those the focus needs that they do not
    trained_regions: list[BodyRegion]
    missing_regions: list[BodyRegion]
    # the main exercises that count towards the focus, and how many it needs
    main_exercises_counted: int
    main_exercises_required: int
    limitations: list[CoverageLimitation]


class ProposedExerciseResponse(BaseModel):
    exercise_order: int
    # the warm-up, the main workout or the cool-down
    section: PlanSection
    exercise_id: int
    exercise_name: str
    # what the exercise needs, from the catalog; empty when nothing
    equipment: list[str]
    sets: int
    # each set's target: reps, or a duration in seconds (one of them)
    reps: int | None
    duration_seconds: int | None
    rest_seconds: int | None
    # in kg: the weight the saved plan has for it, carried on, or the one the user
    # gave; null for none (always given, so a client never infers it)
    weight_kg: float | None
    notes: str | None


class WorkoutPlanProposalResponse(BaseModel):
    """A workout plan the coach proposed to the signed-in user: a warm-up, the
    main workout and a cool-down. It is not saved: approving it, with POST
    /coach/proposals/{proposal_id}/approve and its binding, saves all of it as
    a PLANNED plan (and cancels the plan it revises, when it revises one)."""

    proposal_id: str
    # the digest of this exact proposal, every section included: an approval
    # must carry it
    binding: str
    expires_at: datetime
    name: str
    scheduled_date: date
    # ordered by exercise_order: the warm-up, the main workout, the cool-down
    exercises: list[ProposedExerciseResponse]
    # Formiq's estimate of how long each section takes, and the whole workout
    warm_up_minutes: int
    main_minutes: int
    cool_down_minutes: int
    estimated_minutes: int
    # whether the main workout fulfils its focus, and what is missing when not
    coverage: ProposalCoverage
    # the saved plan it would replace, when it revises one; null for a new workout
    revision: ProposalRevisionResponse | None = None
    # how it differs from that plan, as the plan is now; null for a new workout,
    # and when the plan is not as it was when proposed (approving would then be
    # refused), so a change is never listed that the plan does not show
    changes: ProposalChanges | None = None


class CoachMessageResponse(BaseModel):
    reply: str
    # only when the coach proposed a workout plan in this reply
    proposal: WorkoutPlanProposalResponse | None = None


class PendingProposalResponse(WorkoutPlanProposalResponse):
    """A proposal that still awaits the user's approval, as GET
    /coach/proposals/pending lists it: the same card and the same binding as
    when it was shown."""

    created_at: datetime


class PendingProposalsResponse(BaseModel):
    """The user's proposals that can still be approved, the most recently made
    first; none is the empty list."""

    proposals: list[PendingProposalResponse]


class ProposalApprovalRequest(BaseModel):
    """The user's approval of a proposed plan, as it was shown to them."""

    model_config = ConfigDict(extra="forbid")

    binding: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ProposalRejectionRequest(ProposalApprovalRequest):
    """The user's rejection of a proposed plan, as it was shown to them."""
