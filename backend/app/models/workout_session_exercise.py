from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workout_session import WorkoutSession
    from app.models.workout_set import WorkoutSet


class WorkoutSessionExercise(Base):
    """An exercise actually performed in a session.

    exercise_id is the exercise performed; plan_exercise_id optionally links
    the exercise that was planned, which may differ (a substitution). The same
    exercise may appear more than once in a session, at different positions.
    """

    __tablename__ = "workout_session_exercises"
    # Its index, which starts with workout_session_id, also serves loading a
    # session's exercises and deleting them with the session.
    __table_args__ = (UniqueConstraint("workout_session_id", "exercise_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # deleted with their session (CASCADE)
    workout_session_id: Mapped[int] = mapped_column(
        ForeignKey("workout_sessions.id", ondelete="CASCADE")
    )
    # The planned exercise, if any. Deleting it from its plan keeps the
    # session exercise and sets this to NULL. Indexed for that update.
    plan_exercise_id: Mapped[int | None] = mapped_column(
        ForeignKey("workout_plan_exercises.id", ondelete="SET NULL"), index=True
    )
    # Catalog exercises are retired with is_active, not deleted, so one in the
    # history cannot be deleted (RESTRICT). Indexed for that check.
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    exercise_order: Mapped[int]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workout_session: Mapped["WorkoutSession"] = relationship(back_populates="exercises")
    # passive_deletes: the database deletes the exercise's sets with it.
    sets: Mapped[list["WorkoutSet"]] = relationship(
        back_populates="workout_session_exercise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkoutSet.set_number",
    )
