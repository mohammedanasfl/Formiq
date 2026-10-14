from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from app.agent import ConversationTurn
from app.ai import AIProviderError, AIProviderNotConfiguredError
from app.api.dependencies import AIProvider, CoachTracer, CurrentUser, DbSession, Proposals
from app.schemas import (
    CoachMessageRequest,
    CoachMessageResponse,
    ProposalApprovalRequest,
    WorkoutPlanProposalResponse,
    WorkoutPlanResponse,
)
from app.services import CoachService, PlanProposalService
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidWorkoutPlanError,
    ProposalNotApprovableError,
    ProposalNotFoundError,
    UserNotFoundError,
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
        )
    except UserNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
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
    return CoachMessageResponse(
        reply=answer.reply,
        proposal=WorkoutPlanProposalResponse(
            proposal_id=proposal.proposal_id,
            binding=proposal.binding(),
            **shown.model_dump(
                include={
                    "expires_at",
                    "name",
                    "scheduled_date",
                    "exercises",
                    "warm_up_minutes",
                    "main_minutes",
                    "cool_down_minutes",
                    "estimated_minutes",
                    "coverage",
                }
            ),
        ),
    )


@router.post(
    "/proposals/{proposal_id}/approve",
    response_model=WorkoutPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def approve_workout_plan_proposal(
    proposal_id: ProposalId,
    approval: ProposalApprovalRequest,
    current_user: CurrentUser,
    db: DbSession,
    proposals: Proposals,
):
    """The signed-in user approves a workout plan the coach proposed to them,
    as it was shown (its binding): the plan is saved, once, and returned."""
    try:
        return PlanProposalService(db, proposals).approve(
            current_user.id, proposal_id, approval.binding
        )
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
