from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.workout_plan import PlanSection

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
    revision: ProposalRevision | None = None


class CoachMessageResponse(BaseModel):
    reply: str
    # only when the coach proposed a workout plan in this reply
    proposal: WorkoutPlanProposalResponse | None = None


class ProposalApprovalRequest(BaseModel):
    """The user's approval of a proposed plan, as it was shown to them."""

    model_config = ConfigDict(extra="forbid")

    binding: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
