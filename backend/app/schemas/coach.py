from datetime import date, datetime
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
    a PLANNED plan."""

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


class CoachMessageResponse(BaseModel):
    reply: str
    # only when the coach proposed a workout plan in this reply
    proposal: WorkoutPlanProposalResponse | None = None


class ProposalApprovalRequest(BaseModel):
    """The user's approval of a proposed plan, as it was shown to them."""

    model_config = ConfigDict(extra="forbid")

    binding: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
