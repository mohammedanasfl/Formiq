from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workout_session_exercise import WorkoutSessionExercise


class WorkoutSession(Base):
    """A workout the user actually did, or is doing: execution, not the plan.

    It stays readable when its plan changes or is deleted, so it does not
    depend on the plan for its history.
    """

    __tablename__ = "workout_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A user with workout history cannot be deleted (RESTRICT). Indexed for
    # listing a user's sessions.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    # The plan the session followed, if any; NULL for a manual workout or once
    # the plan is deleted (SET NULL), which keeps the session. Indexed for that
    # update when a plan is deleted.
    workout_plan_id: Mapped[int | None] = mapped_column(
        ForeignKey("workout_plans.id", ondelete="SET NULL"), index=True
    )
    # set by the database when the session starts, not by the client
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # set by the service when the session is completed
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # a WorkoutSessionStatus value (app.schemas.workout_session), validated by the schemas
    status: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # passive_deletes: the database deletes the session's exercises with it.
    exercises: Mapped[list["WorkoutSessionExercise"]] = relationship(
        back_populates="workout_session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkoutSessionExercise.exercise_order",
    )
