from enum import StrEnum

from sqlalchemy.orm import Session

from app.agent.safety import SAFE
from app.approvals import (
    ProposalTerms,
    WriteAction,
    WriteProposal,
    restore,
    safety_of,
)
from app.models import WorkoutPlan, WorkoutPlanProposal
from app.repositories import WorkoutPlanProposalRepository
from app.schemas import WorkoutPlanCreate, WorkoutPlanStatus
from app.services.exceptions import ProposalNotApprovableError, ProposalNotFoundError
from app.services.workout_plan_service import WorkoutPlanService


class ProposalStatus(StrEnum):
    # waiting for the user's approval, until it expires
    PENDING = "PENDING"
    # approved: its plan is saved, and it approves nothing more
    APPROVED = "APPROVED"


EXPIRED = "this proposal has expired: ask the coach for a new one"
CHANGED = "this approval is for a different version of the proposal than the one proposed"
ALREADY_APPROVED = "this proposal was already approved"
NOT_APPROVABLE = "this proposal cannot be approved"
REPLACED_PLAN_CHANGED = (
    "the workout plan this proposal replaces was changed or cancelled since it was proposed: "
    "ask the coach for a new one"
)


class PlanProposalService:
    """The workout plans the coach proposed, waiting for the user's approval,
    and the approval that saves one.

    The coach service keeps here the proposal it shows the user (register).
    The proposal is a row in the database, so it outlives a restart and every
    worker process sees it. Only the user it was made for may approve it
    (approve), with the binding of the exact proposal they were shown, before
    it expires, and once: the row is locked while it is approved, and the plan
    is created and the proposal used up in one transaction, so two approvals
    at once save one plan, and a failed one saves nothing and uses nothing up.
    A proposal that revises a saved plan cancels it in the same transaction,
    only if it is still PLANNED and as it was when proposed: its row is locked
    too, so two approvals replacing it save one plan. Every check fails
    closed.
    """

    def __init__(self, session: Session, terms: ProposalTerms) -> None:
        self.session = session
        self.terms = terms
        self.proposals = WorkoutPlanProposalRepository(session)
        self.plans = WorkoutPlanService(session)

    def register(self, proposal: WriteProposal) -> None:
        """Keeps the proposal, PENDING, for its user to approve; the user's
        expired proposals that were never approved are cleared."""
        try:
            self.proposals.delete_expired(
                proposal.trusted_user_id, status=ProposalStatus.PENDING, now=self.terms.clock()
            )
            self.proposals.create(
                WorkoutPlanProposal(
                    proposal_id=proposal.proposal_id,
                    user_id=proposal.trusted_user_id,
                    action=proposal.action,
                    parameters=proposal.values(),
                    binding=proposal.binding(),
                    status=ProposalStatus.PENDING,
                    created_at=proposal.created_at,
                    expires_at=proposal.expires_at,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def awaits_approval(self, user_id: int) -> bool:
        """Whether a workout plan proposal of the user's awaits their approval:
        PENDING, and not expired by now. The coach may then point them to it;
        it approves nothing, and approve() checks everything again."""
        return self.proposals.has_unexpired(
            user_id,
            action=WriteAction.CREATE_WORKOUT_PLAN,
            status=ProposalStatus.PENDING,
            now=self.terms.clock(),
        )

    def awaiting_approval(self, user_id: int) -> list[WorkoutPlanProposal]:
        """The user's workout plan proposals awaiting their approval (PENDING,
        not expired by now), the most recently made first: the one the coach
        last showed them is the first. Read for the user of the request only;
        reading one approves nothing, and approve() checks everything again."""
        return self.proposals.list_unexpired(
            user_id,
            action=WriteAction.CREATE_WORKOUT_PLAN,
            status=ProposalStatus.PENDING,
            now=self.terms.clock(),
        )

    def approve(self, user_id: int, proposal_id: str, binding: str) -> WorkoutPlan:
        """Creates the proposed plan for the user, as PLANNED, and cancels the
        plan it revises, if any. binding is the proposal's binding as the user
        was shown it: an approval of anything else approves nothing."""
        try:
            stored = self.proposals.get_for_update(proposal_id)
            # another user's proposal is not told apart from a missing one
            if (
                stored is None
                or stored.user_id != user_id
                or stored.action != WriteAction.CREATE_WORKOUT_PLAN
            ):
                raise ProposalNotFoundError(f"there is no workout plan proposal {proposal_id}")
            proposal = restore(
                proposal_id=stored.proposal_id,
                trusted_user_id=stored.user_id,
                action=WriteAction(stored.action),
                parameters=stored.parameters,
                created_at=stored.created_at,
                expires_at=stored.expires_at,
            )
            # the stored proposal must still be the one its binding was made
            # for, and the user must have been shown that one
            if proposal.binding() != stored.binding:
                raise ProposalNotApprovableError(NOT_APPROVABLE)
            if binding != stored.binding:
                raise ProposalNotApprovableError(CHANGED)
            if stored.status != ProposalStatus.PENDING:
                raise ProposalNotApprovableError(ALREADY_APPROVED)
            now = self.terms.clock()
            if now >= stored.expires_at:
                raise ProposalNotApprovableError(EXPIRED)
            # its own text is checked again, as when it was proposed
            if safety_of(SAFE, proposal.text_values()).enforced:
                raise ProposalNotApprovableError(NOT_APPROVABLE)

            values = proposal.values()
            # the plan it revises, still PLANNED and unchanged, is cancelled with it
            if (replaced_id := values.get("replaces_plan_id")) is not None:
                replaced = self.plans.lock_plan(user_id, replaced_id)
                if (
                    replaced is None
                    or replaced.status != WorkoutPlanStatus.PLANNED
                    or self.plans.version_of(replaced) != values.get("replaces_plan_digest")
                ):
                    raise ProposalNotApprovableError(REPLACED_PLAN_CHANGED)
                self.plans.cancel_locked(replaced)
            plan = self.plans.add_plan(
                user_id,
                WorkoutPlanCreate(
                    name=values["name"],
                    status=WorkoutPlanStatus.PLANNED,
                    scheduled_date=values["scheduled_date"],
                    exercises=values["exercises"],
                ),
            )
            stored.status = ProposalStatus.APPROVED
            stored.approved_at = now
            stored.workout_plan_id = plan.id
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(plan)
        return plan
