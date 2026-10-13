import uuid

from sqlalchemy.orm import Session

from app.agent.safety import SAFE
from app.approvals import (
    ApprovalEvent,
    ApprovalSource,
    ApprovalState,
    ApprovalStore,
    Authorization,
    AuthorizationFailure,
    UserDecision,
    WriteAction,
)
from app.models import WorkoutPlan
from app.schemas import WorkoutPlanCreate, WorkoutPlanStatus
from app.services.exceptions import ProposalNotApprovableError, ProposalNotFoundError
from app.services.workout_plan_service import WorkoutPlanService


class PlanProposalService:
    """Saves a workout plan the coach proposed, when the user approves it.

    The approval goes through the approval store the proposal was registered in
    (app.approvals.store): only this user's approval of this exact proposal,
    once and before it expires, lets the plan be created, through
    WorkoutPlanService and its rules.
    """

    def __init__(self, session: Session, approvals: ApprovalStore) -> None:
        self.plans = WorkoutPlanService(session)
        self.approvals = approvals

    def approve(self, user_id: int, proposal_id: str, binding: str) -> WorkoutPlan:
        """Creates the proposed plan for the user. binding is the proposal's
        binding as the user was shown it: an approval of anything else
        approves nothing."""
        found = self.approvals.find(proposal_id)
        if found is None:
            raise ProposalNotFoundError(f"there is no workout plan proposal {proposal_id}")
        approval_id, proposal = found
        # another user's proposal is not told apart from a missing one
        if (
            proposal.trusted_user_id != user_id
            or proposal.action is not WriteAction.CREATE_WORKOUT_PLAN
        ):
            raise ProposalNotFoundError(f"there is no workout plan proposal {proposal_id}")

        decided = self.approvals.record(
            ApprovalEvent(
                event_id=uuid.uuid4().hex,
                approval_id=approval_id,
                proposal_id=proposal_id,
                user_id=user_id,
                binding=binding,
                decision=UserDecision.APPROVE,
                source=ApprovalSource.USER_ACTION,
            )
        )
        if not decided.allowed:
            raise ProposalNotApprovableError(refusal(decided))
        # Used up before the plan is created: the approval allows one plan, even
        # if creating it then fails.
        authorized = self.approvals.consume(
            proposal, approval_id, trusted_user_id=user_id, request=SAFE, current_version=None
        )
        if not authorized.allowed:
            raise ProposalNotApprovableError(refusal(authorized))

        values = proposal.values()
        return self.plans.create_plan(
            user_id,
            WorkoutPlanCreate(
                name=values["name"],
                status=WorkoutPlanStatus.PLANNED,
                scheduled_date=values["scheduled_date"],
                exercises=values["exercises"],
            ),
        )


def refusal(authorization: Authorization) -> str:
    """Why the approval was refused, for the user: never a value of the proposal."""
    if authorization.state is ApprovalState.EXPIRED:
        return "this proposal has expired: ask the coach for a new one"
    if authorization.failure is AuthorizationFailure.PROPOSAL_CHANGED:
        return "this approval is for a different version of the proposal than the one proposed"
    if authorization.state in (ApprovalState.APPROVED, ApprovalState.CONSUMED):
        return "this proposal was already approved"
    return "this proposal cannot be approved"
