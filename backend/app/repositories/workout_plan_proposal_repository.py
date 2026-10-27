from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import WorkoutPlanProposal


class WorkoutPlanProposalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, proposal: WorkoutPlanProposal) -> WorkoutPlanProposal:
        self.session.add(proposal)
        self.session.flush()
        return proposal

    def get_for_update(self, proposal_id: str) -> WorkoutPlanProposal | None:
        """The proposal, with its row locked until the transaction ends: a
        second approval of it waits, then sees what the first one did."""
        return self.session.scalars(
            select(WorkoutPlanProposal)
            .where(WorkoutPlanProposal.proposal_id == proposal_id)
            .with_for_update()
        ).one_or_none()

    def list_unexpired(
        self, user_id: int, *, action: str, status: str, now: datetime
    ) -> list[WorkoutPlanProposal]:
        """The user's proposals of this action, in this status, that have not
        expired by now: the most recently made first."""
        return list(
            self.session.scalars(
                select(WorkoutPlanProposal)
                .where(
                    WorkoutPlanProposal.user_id == user_id,
                    WorkoutPlanProposal.action == action,
                    WorkoutPlanProposal.status == status,
                    WorkoutPlanProposal.expires_at > now,
                )
                .order_by(
                    WorkoutPlanProposal.created_at.desc(),
                    WorkoutPlanProposal.recorded_at.desc(),
                )
            )
        )

    def delete_expired(self, user_id: int, *, status: str, now: datetime) -> None:
        """Deletes the user's proposals in this status that expired by now."""
        self.session.execute(
            delete(WorkoutPlanProposal).where(
                WorkoutPlanProposal.user_id == user_id,
                WorkoutPlanProposal.status == status,
                WorkoutPlanProposal.expires_at <= now,
            )
        )

    def supersede_pending(
        self, user_id: int, *, action: str, replaces_plan_id: int, keep: str, status: str
    ) -> list[str]:
        """Sets the user's PENDING proposals of this action that revise this saved plan to
        `status`, except the proposal `keep`: the ones a newer proposal for the same plan
        replaces. Only a proposal of this user that revises exactly this plan is touched (a new
        workout, another plan's revision and another user's proposal are not). Returns the ids
        it changed."""
        return list(
            self.session.scalars(
                update(WorkoutPlanProposal)
                .where(
                    WorkoutPlanProposal.user_id == user_id,
                    WorkoutPlanProposal.action == action,
                    WorkoutPlanProposal.status == "PENDING",
                    WorkoutPlanProposal.proposal_id != keep,
                    WorkoutPlanProposal.parameters["replaces_plan_id"].astext
                    == str(replaces_plan_id),
                )
                .values(status=status)
                .returning(WorkoutPlanProposal.proposal_id)
                # the session holds no stale copy of these rows: they are read again by id
                .execution_options(synchronize_session=False)
            )
        )

    def approved_plan_ids(self, user_id: int, *, action: str, limit: int) -> list[int]:
        """The ids of the plans the user's approved proposals of this action saved, the most
        recent first (at most limit): what Formiq's records say an approval saved."""
        return list(
            self.session.scalars(
                select(WorkoutPlanProposal.workout_plan_id)
                .where(
                    WorkoutPlanProposal.user_id == user_id,
                    WorkoutPlanProposal.action == action,
                    WorkoutPlanProposal.status == "APPROVED",
                    WorkoutPlanProposal.workout_plan_id.is_not(None),
                )
                .order_by(WorkoutPlanProposal.approved_at.desc())
                .limit(limit)
            )
        )
