from datetime import datetime

from sqlalchemy import delete, select
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

    def delete_expired(self, user_id: int, *, status: str, now: datetime) -> None:
        """Deletes the user's proposals in this status that expired by now."""
        self.session.execute(
            delete(WorkoutPlanProposal).where(
                WorkoutPlanProposal.user_id == user_id,
                WorkoutPlanProposal.status == status,
                WorkoutPlanProposal.expires_at <= now,
            )
        )
