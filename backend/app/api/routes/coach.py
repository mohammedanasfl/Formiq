from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response, status

from app.agent import ConversationTurn
from app.ai import AIProviderError, AIProviderNotConfiguredError
from app.api.dependencies import AIProvider, CoachTracer, CurrentUser, DbSession, Proposals
from app.schemas import (
    CoachMessageRequest,
    CoachMessageResponse,
    PendingProposalsResponse,
    ProposalApprovalRequest,
    ProposalRejectionRequest,
    WorkoutPlanResponse,
)
from app.services import CoachService, PlanProposalService
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidWorkoutPlanError,
    ProposalNotApprovableError,
    ProposalNotFoundError,
    ProposalNotRejectableError,
    UserNotFoundError,
    WorkoutPlanNotFoundError,
    WorkoutPlanNotRevisableError,
)

router = APIRouter(prefix="/coach", tags=["coach"])

# Formiq's proposal ids: 32 lowercase hex digits
ProposalId = Annotated[str, Path(pattern=r"^[0-9a-f]{32}$")]


# exclude_unset: a reply without a proposal is {"reply": ...}, as before
@router.post("/message", response_model=CoachMessageResponse, response_model_exclude_unset=True)
def send_coach_message(
    message_data: CoachMessageRequest,
    current_user: CurrentUser,
    db: DbSession,
    provider: AIProvider,
    tracer: CoachTracer,
    proposals: Proposals,
):
    # The coach acts for the signed-in user only: its id is the one the access
    # token was issued for, and the body has no field that could name another.
    try:
        answer = CoachService(db, provider, tracer, proposals).answer(
            current_user.id,
            message_data.message,
            [ConversationTurn(turn.role, turn.text) for turn in message_data.history],
            message_data.workout_plan_id,
            message_data.timezone,
        )
    except (UserNotFoundError, WorkoutPlanNotFoundError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    # the plan the user opened the coach to change is not one it may change
    except WorkoutPlanNotRevisableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    # The provider errors' own messages stay in the server log: the client only
    # learns that the coach is unavailable.
    except AIProviderNotConfiguredError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="the AI coach is not configured",
        ) from error
    except AIProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="the AI coach could not answer; try again later",
        ) from error
    if answer.proposal is None:
        return CoachMessageResponse(reply=answer.reply)
    proposal, shown = answer.proposal
    # with what it replaces, read now: revision and changes are always given
    # (null for a new workout), so a client never infers them
    return CoachMessageResponse(
        reply=answer.reply,
        proposal=PlanProposalService(db, proposals).present(proposal, shown),
    )


@router.get("/proposals/pending", response_model=PendingProposalsResponse)
def list_pending_proposals(current_user: CurrentUser, db: DbSession, proposals: Proposals):
    """The signed-in user's workout plan proposals that can still be approved,
    the most recently made first, as they were shown (the same binding): for a
    client that lost them, such as after a restart. It proposes, approves and
    changes nothing."""
    return PendingProposalsResponse(
        proposals=PlanProposalService(db, proposals).pending(current_user.id)
    )


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=WorkoutPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def approve_workout_plan_proposal(
    proposal_id: ProposalId,
    approval: ProposalApprovalRequest,
    response: Response,
    current_user: CurrentUser,
    db: DbSession,
    proposals: Proposals,
):
    """The signed-in user approves a workout plan the coach proposed to them,
    as it was shown (its binding): the plan is saved, once, and returned (201).
    Approving a proposal they already approved saves nothing more: it returns
    the plan that approval saved (200), while it is still as it was saved."""
    try:
        approved = PlanProposalService(db, proposals).approve(
            current_user.id, proposal_id, approval.binding
        )
        if not approved.created:
            response.status_code = status.HTTP_200_OK
        return approved.plan
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ProposalNotApprovableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    # the catalog or the plan rules changed since the proposal was made
    except (ExerciseNotFoundError, InactiveExerciseError, InvalidWorkoutPlanError) as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"this proposal can no longer be saved: {error}",
        ) from error


@router.post("/proposals/{proposal_id}/reject", status_code=status.HTTP_204_NO_CONTENT)
def reject_workout_plan_proposal(
    proposal_id: ProposalId,
    rejection: ProposalRejectionRequest,
    current_user: CurrentUser,
    db: DbSession,
    proposals: Proposals,
):
    """The signed-in user rejects a workout plan the coach proposed to them, as
    it was shown (its binding): it can then no longer be approved. Rejecting it
    again is no error (204) for as long as the proposal is kept, an expired one
    included; once an expired proposal is cleared it is a 404, as is another
    user's or one that never was. One that was approved cannot be rejected."""
    try:
        PlanProposalService(db, proposals).reject(current_user.id, proposal_id, rejection.binding)
    except ProposalNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ProposalNotRejectableError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
