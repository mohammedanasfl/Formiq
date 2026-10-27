from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkoutPlanProposal(Base):
    """A workout plan the coach proposed to a user, waiting for their approval
    (app.services.plan_proposal_service). It is not a plan: approving it,
    once and before it expires, creates the plan.

    Kept in the database, so a proposal outlives a restart and every worker
    process sees the same one; the row is locked while it is approved, so two
    approvals at once save one plan.
    """

    __tablename__ = "workout_plan_proposals"

    # Formiq's proposal id (32 hex digits), shown to the user
    proposal_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    # the user the proposal was made for, from the coach request's token;
    # indexed for clearing a user's expired proposals
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # a WriteAction value (app.approvals): create_workout_plan
    action: Mapped[str] = mapped_column(String(40))
    # the proposed values, as plain JSON (app.approvals.WriteProposal.values())
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # the digest of the exact proposal the user was shown: an approval must carry it
    binding: Mapped[str] = mapped_column(String(64))
    # a ProposalStatus value: PENDING until approved, rejected or expired; APPROVED once its
    # plan is saved; REJECTED when the user rejected it. A plain string column with no
    # constraint on its values, so a status added later needs no migration.
    status: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # the plan its approval saved
    workout_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("workout_plans.id", ondelete="SET NULL")
    )
    # when the row was written, by the database's clock
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
