import logging
from datetime import date, datetime
from enum import StrEnum
from typing import Any, NamedTuple

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
from app.observability.trajectory import log_proposal_approved
from app.repositories import UserRepository, WorkoutPlanProposalRepository
from app.schemas import WorkoutPlanCreate, WorkoutPlanStatus
from app.schemas.coach import (
    PendingProposalResponse,
    ProposalCoverage,
    ProposalRevision,
    ProposalRevisionResponse,
    WorkoutPlanProposalResponse,
)
from app.schemas.workout_plan import PlanSection
from app.services.exceptions import (
    ProposalNotApprovableError,
    ProposalNotFoundError,
    ProposalNotRejectableError,
)
from app.services.exercise_catalog_service import ExerciseCatalogService
from app.services.workout_plan_service import WorkoutPlanService
from app.tools.proposal_view import ProposalViewBuilder, ReplacedPlan, StoredProposalView
from app.tools.schemas import ProposedExerciseOutput, ProposedWorkoutPlanOutput


logger = logging.getLogger(__name__)


class ProposalStatus(StrEnum):
    # waiting for the user's approval, until it expires
    PENDING = "PENDING"
    # approved: its plan is saved, and it approves nothing more
    APPROVED = "APPROVED"
    # rejected by the user: it approves nothing, and the coach no longer sees it
    REJECTED = "REJECTED"
    # replaced by a newer proposal for the same saved plan (Phase 2.7): it approves nothing, and
    # neither the user's list nor the coach sees it. A status of the existing text column.
    SUPERSEDED = "SUPERSEDED"


class Approval(NamedTuple):
    plan: WorkoutPlan
    # False when the proposal had been approved before: this is the plan that
    # approval saved, found again for a client that never got its answer
    created: bool


class Approvable(NamedTuple):
    """A stored proposal that still awaits the user's approval, and how it reads
    back now (its exercises, minutes, coverage and the plan it replaces)."""

    stored: WorkoutPlanProposal
    view: StoredProposalView


# how many of a user's latest approved proposals the coach's reply check knows the plans of
MAX_APPROVED_PLANS = 50
EXPIRED = "this proposal has expired: ask the coach for a new one"
CHANGED = "this approval is for a different version of the proposal than the one proposed"
APPROVED_PLAN_CHANGED = (
    "this proposal was already approved, but the workout plan it saved was changed, cancelled "
    "or removed since"
)
REJECTED_PROPOSAL = "this proposal was rejected: ask the coach for a new one"
SUPERSEDED_PROPOSAL = (
    "this proposal was replaced by a newer proposal for the same workout: review the newer one, "
    "or ask the coach for a new one"
)
NOT_APPROVABLE = "this proposal cannot be approved"
REJECTION_CHANGED = "this rejection is for a different version of the proposal than the one proposed"
APPROVED_NOT_REJECTABLE = "this proposal was already approved: it cannot be rejected"
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

    An approval is safe to repeat: when the same user sends the binding of a
    proposal that was approved, they get the plan that approval saved (a
    client whose answer was lost learns what happened), if that plan is still
    PLANNED and as the proposal made it; otherwise a conflict, never a second
    plan. The user may instead reject a proposal that has not been approved
    (reject): it is then never approved, and no longer waits.

    The proposal's states: PENDING until it is approved, rejected or superseded,
    or 30 minutes old (it is then expired, and cleared when its user next gets a
    proposal); APPROVED once its plan is saved; REJECTED; SUPERSEDED.

    A proposal that revises a saved plan supersedes the user's earlier PENDING
    proposals that revise the same plan (register), so a refinement never leaves
    two competing versions of one workout to approve. Only those: a new workout,
    another plan's proposal and another user's are untouched, and so is one
    already approved or rejected. The user's proposals are registered one at a
    time (their row is locked), so two refinements at once leave one PENDING.

    One rule says which proposals still await the user's approval
    (approvable): the ones approve() would not refuse for the proposal itself.
    The list the user is offered (pending) and what the coach reads and points
    them to (awaiting_approval) are both made from it, so the coach never shows
    a proposal the user could not approve.
    """

    def __init__(self, session: Session, terms: ProposalTerms) -> None:
        self.session = session
        self.terms = terms
        self.proposals = WorkoutPlanProposalRepository(session)
        self.plans = WorkoutPlanService(session)

    def register(self, proposal: WriteProposal) -> None:
        """Keeps the proposal, PENDING, for its user to approve; the user's
        expired proposals that were never approved (pending, rejected or
        superseded) are cleared. A proposal that revises a saved plan
        supersedes the user's earlier PENDING proposals for the same plan: they
        approve nothing from now on, and what they replaced is left as it is.
        Registered one at a time for each user: their row is locked until the
        commit (FOR NO KEY UPDATE: their other rows can still be written)."""
        try:
            now = self.terms.clock()
            user_id = proposal.trusted_user_id
            UserRepository(self.session).get_by_id_for_update(user_id)
            for status in (ProposalStatus.PENDING, ProposalStatus.REJECTED, ProposalStatus.SUPERSEDED):
                self.proposals.delete_expired(user_id, status=status, now=now)
            self.proposals.create(
                WorkoutPlanProposal(
                    proposal_id=proposal.proposal_id,
                    user_id=user_id,
                    action=proposal.action,
                    parameters=proposal.values(),
                    binding=proposal.binding(),
                    status=ProposalStatus.PENDING,
                    created_at=proposal.created_at,
                    expires_at=proposal.expires_at,
                )
            )
            replaced = proposal.values().get("replaces_plan_id")
            superseded = (
                []
                if replaced is None
                else self.proposals.supersede_pending(
                    user_id,
                    action=proposal.action,
                    replaces_plan_id=replaced,
                    keep=proposal.proposal_id,
                    status=ProposalStatus.SUPERSEDED,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
        if superseded:
            logger.info(
                "Workout proposal %s supersedes %s for plan %s",
                proposal.proposal_id[:8],
                ", ".join(item[:8] for item in superseded),
                replaced,
            )

    def awaits_approval(self, user_id: int, *, revising: int | None = None) -> bool:
        """Whether a workout plan proposal of the user's awaits their approval
        (approvable). The coach may then point them to it; it approves nothing,
        and approve() checks everything again."""
        return bool(self.awaiting_approval(user_id, revising=revising))

    def awaiting_approval(
        self, user_id: int, *, revising: int | None = None
    ) -> list[WorkoutPlanProposal]:
        """The user's workout plan proposals awaiting their approval
        (approvable), the most recently made first: the one the coach last
        showed them is the first. With revising, only those that revise that
        saved plan (a newer version of its workout); a new workout and another
        plan's revision are not about it. Read for the user of the request
        only; reading one approves nothing, and approve() checks everything
        again."""
        return [item.stored for item in self.approvable(user_id, revising=revising)]

    def approvable(self, user_id: int, *, revising: int | None = None) -> list[Approvable]:
        """The user's proposals that approve() would not refuse for the proposal
        itself, the most recently made first, each with its stored view: PENDING
        and unexpired, still as stored (its binding matches), its own text safe
        again, its exercises still active, one made since Formiq recorded what it
        is for (its focus), and, for a revision, a plan that is still PLANNED and
        as it was proposed. Left out: expired, approved, rejected, changed,
        unsafe and stale ones. A stored proposal that cannot be read back is
        left out too, and logged by its short reference: nothing fails for it.

        With revising, only the proposals that revise that plan. It reads only:
        nothing is proposed, approved, rejected or changed."""
        now = self.terms.clock()
        views = self._views()
        found = []
        for stored in self.proposals.list_unexpired(
            user_id,
            action=WriteAction.CREATE_WORKOUT_PLAN,
            status=ProposalStatus.PENDING,
            now=now,
        ):
            try:
                proposal = self._restored(stored)
                if proposal.binding() != stored.binding or self._refusal(stored, proposal, now):
                    continue
                view = views.stored(user_id, stored.parameters)
            except (KeyError, TypeError, ValueError):
                logger.warning("Workout proposal %s cannot be read back", stored.proposal_id[:8])
                continue
            if view.coverage is None or not view.exercises_available:
                continue
            if view.replaces_plan_id is not None and not (
                view.replaced is not None
                and view.replaced.revision is not None
                and view.replaced.unchanged
            ):
                continue
            if revising is not None and view.replaces_plan_id != revising:
                continue
            found.append(Approvable(stored, view))
        return found

    def present(
        self, proposal: WriteProposal, shown: ProposedWorkoutPlanOutput
    ) -> WorkoutPlanProposalResponse:
        """The proposal the coach shows the user in its reply (shown is how the
        coach described it), as the API answers: for a revision also how it
        differs from the plan it replaces and how long that plan takes, read
        now. They are given only while the plan is still as it was when the
        proposal was made, so a client is never shown a comparison with a plan
        the proposal was not made against."""
        replaced = None
        if shown.revision is not None:
            replaced = self._views().replaced(
                proposal.trusted_user_id,
                proposal.values(),
                name=shown.name,
                scheduled_date=shown.scheduled_date,
                exercises=shown.exercises,
            )
        return self._response(
            WorkoutPlanProposalResponse,
            proposal_id=proposal.proposal_id,
            binding=proposal.binding(),
            expires_at=shown.expires_at,
            name=shown.name,
            scheduled_date=shown.scheduled_date,
            exercises=shown.exercises,
            minutes={
                PlanSection.WARM_UP: shown.warm_up_minutes,
                PlanSection.MAIN_WORKOUT: shown.main_minutes,
                PlanSection.COOL_DOWN: shown.cool_down_minutes,
            },
            coverage=shown.coverage,
            revision=shown.revision,
            replaced=replaced,
        )

    def approved_plan_ids(self, user_id: int) -> frozenset[int]:
        """The ids of the plans an approval of the user's saved (its proposal is APPROVED and
        names the plan), the latest MAX_APPROVED_PLANS of them: what the coach's reply may
        call applied. Read for the user of the request only; it changes nothing."""
        return frozenset(
            self.proposals.approved_plan_ids(
                user_id, action=WriteAction.CREATE_WORKOUT_PLAN, limit=MAX_APPROVED_PLANS
            )
        )

    def pending(self, user_id: int) -> list[PendingProposalResponse]:
        """The user's proposals that can be approved now (approvable), the most
        recently made first, each as it was shown, with the same binding. For the
        user only. It reads only: nothing is proposed, approved or changed."""
        return [
            self._response(
                PendingProposalResponse,
                proposal_id=item.stored.proposal_id,
                binding=item.stored.binding,
                expires_at=item.stored.expires_at,
                name=item.view.name,
                scheduled_date=item.view.scheduled_date,
                exercises=item.view.exercises,
                minutes=item.view.minutes,
                coverage=item.view.coverage,
                revision=None if item.view.replaced is None else item.view.replaced.revision,
                replaced=item.view.replaced,
                created_at=item.stored.created_at,
            )
            for item in self.approvable(user_id)
        ]

    def approve(self, user_id: int, proposal_id: str, binding: str) -> Approval:
        """Creates the proposed plan for the user, as PLANNED, and cancels the
        plan it revises, if any. binding is the proposal's binding as the user
        was shown it: an approval of anything else approves nothing.

        A proposal the user already approved is not approved again: the plan
        that approval saved is returned (created=False) when it is still
        PLANNED and prescribes what the proposal did, so a lost answer can be
        recovered; if it was changed, cancelled or removed since, the approval
        is refused."""
        try:
            stored = self._locked(user_id, proposal_id)
            proposal = self._restored(stored)
            # the stored proposal must still be the one its binding was made
            # for, and the user must have been shown that one
            if proposal.binding() != stored.binding:
                raise ProposalNotApprovableError(NOT_APPROVABLE)
            if binding != stored.binding:
                raise ProposalNotApprovableError(CHANGED)
            if stored.status == ProposalStatus.APPROVED:
                saved = self._saved_plan(user_id, stored, proposal.values())
                if saved is None:
                    raise ProposalNotApprovableError(APPROVED_PLAN_CHANGED)
                # nothing was changed: end the transaction, which frees the row
                self.session.rollback()
                self.session.refresh(saved)
                return Approval(saved, created=False)
            now = self.terms.clock()
            if refusal := self._refusal(stored, proposal, now):
                raise ProposalNotApprovableError(refusal)

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
        # after the commit: only an approval that saved a plan is an approval event
        log_proposal_approved(proposal_ref=proposal_id, plan_id=plan.id)
        return Approval(plan, created=True)

    def reject(self, user_id: int, proposal_id: str, binding: str) -> None:
        """The user rejects the proposal, as they were shown it (its binding):
        it is REJECTED, so it can no longer be approved and no longer waits.
        Rejecting again changes nothing, for as long as its row is kept. A
        proposal already approved is not rejected: its plan is saved. It is
        not required to be unexpired: an expired proposal is as good as
        rejected, and is cleared with the user's next one, after which it is a
        proposal that is not there (ProposalNotFoundError, like another user's
        or one that never was)."""
        try:
            stored = self._locked(user_id, proposal_id)
            if binding != stored.binding:
                raise ProposalNotRejectableError(REJECTION_CHANGED)
            if stored.status == ProposalStatus.APPROVED:
                raise ProposalNotRejectableError(APPROVED_NOT_REJECTABLE)
            # a superseded proposal approves nothing already: rejecting it changes nothing
            if stored.status != ProposalStatus.SUPERSEDED:
                stored.status = ProposalStatus.REJECTED
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def _locked(self, user_id: int, proposal_id: str) -> WorkoutPlanProposal:
        """The user's proposal, its row locked until the transaction ends.
        Another user's is not told apart from a missing one."""
        stored = self.proposals.get_for_update(proposal_id)
        if (
            stored is None
            or stored.user_id != user_id
            or stored.action != WriteAction.CREATE_WORKOUT_PLAN
        ):
            raise ProposalNotFoundError(f"there is no workout plan proposal {proposal_id}")
        return stored

    @staticmethod
    def _restored(stored: WorkoutPlanProposal) -> WriteProposal:
        return restore(
            proposal_id=stored.proposal_id,
            trusted_user_id=stored.user_id,
            action=WriteAction(stored.action),
            parameters=stored.parameters,
            created_at=stored.created_at,
            expires_at=stored.expires_at,
        )

    @staticmethod
    def _refusal(stored: WorkoutPlanProposal, proposal: WriteProposal, now: datetime) -> str | None:
        """Why no one can approve this stored proposal now, or None: it was
        rejected or is not pending, it has expired, or its own text is
        unsafe, checked again as when it was proposed. What it replaces, and
        its exercises, are checked where they are read."""
        if stored.status == ProposalStatus.REJECTED:
            return REJECTED_PROPOSAL
        if stored.status == ProposalStatus.SUPERSEDED:
            return SUPERSEDED_PROPOSAL
        if stored.status != ProposalStatus.PENDING:
            return NOT_APPROVABLE
        if now >= stored.expires_at:
            return EXPIRED
        if safety_of(SAFE, proposal.text_values()).enforced:
            return NOT_APPROVABLE
        return None

    def _saved_plan(
        self, user_id: int, stored: WorkoutPlanProposal, values: dict[str, Any]
    ) -> WorkoutPlan | None:
        """The plan an approved proposal saved, if it is still the user's, still
        PLANNED and still prescribes exactly what the proposal did."""
        if stored.workout_plan_id is None:
            return None
        plan = self.plans.get_plan(user_id, stored.workout_plan_id)
        if plan is None or plan.status != WorkoutPlanStatus.PLANNED:
            return None
        if plan.name != values["name"] or (
            plan.scheduled_date is None or plan.scheduled_date.isoformat() != values["scheduled_date"]
        ):
            return None
        saved = [
            (
                item.exercise_order, item.section, item.exercise_id, item.sets, item.reps,
                item.duration_seconds, item.rest_seconds, item.weight_kg, item.notes,
            )
            for item in sorted(plan.exercises, key=lambda item: (item.exercise_order, item.id))
        ]  # fmt: skip
        proposed = [
            (
                item["exercise_order"], item["section"], item["exercise_id"], item["sets"],
                item.get("reps"), item.get("duration_seconds"), item.get("rest_seconds"),
                item.get("weight_kg"), item.get("notes"),
            )
            for item in sorted(values["exercises"], key=lambda item: item["exercise_order"])
        ]  # fmt: skip
        return plan if saved == proposed else None

    def _views(self) -> ProposalViewBuilder:
        return ProposalViewBuilder(ExerciseCatalogService(self.session), self.plans)

    @staticmethod
    def _response(
        response: type[WorkoutPlanProposalResponse],
        *,
        proposal_id: str,
        binding: str,
        expires_at: datetime,
        name: str,
        scheduled_date: date,
        exercises: list[ProposedExerciseOutput],
        minutes: dict[PlanSection, int],
        coverage: ProposalCoverage,
        revision: ProposalRevision | None,
        replaced: ReplacedPlan | None,
        **more: Any,
    ) -> Any:
        """The proposal as the API answers. What it replaces is compared with
        only while that plan is as it was when proposed (replaced.unchanged);
        otherwise the comparison and the plan's length are null, not guessed.
        revision and changes are always given, so a client never infers them."""
        current = replaced if replaced is not None and replaced.unchanged else None
        return response(
            proposal_id=proposal_id,
            binding=binding,
            expires_at=expires_at,
            name=name,
            scheduled_date=scheduled_date,
            exercises=[item.model_dump() for item in exercises],
            warm_up_minutes=minutes[PlanSection.WARM_UP],
            main_minutes=minutes[PlanSection.MAIN_WORKOUT],
            cool_down_minutes=minutes[PlanSection.COOL_DOWN],
            estimated_minutes=sum(minutes.values()),
            coverage=coverage,
            revision=None
            if revision is None
            else ProposalRevisionResponse(
                **revision.model_dump(),
                replaces_plan_estimated_minutes=None if current is None else current.minutes,
            ),
            changes=None if current is None else current.changes,
            **more,
        )
