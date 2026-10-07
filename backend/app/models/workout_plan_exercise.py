from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workout_plan import WorkoutPlan


class WorkoutPlanExercise(Base):
    """An exercise prescribed in a workout plan: the target sets, reps, weight
    and rest, not the performed ones.

    The same exercise may appear more than once in a plan, at different
    positions; each position (exercise_order) is used once per plan.
    """

    __tablename__ = "workout_plan_exercises"
    # Its index, which starts with workout_plan_id, also serves loading a
    # plan's exercises and deleting them with the plan.
    __table_args__ = (UniqueConstraint("workout_plan_id", "exercise_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # deleted with their plan (CASCADE)
    workout_plan_id: Mapped[int] = mapped_column(
        ForeignKey("workout_plans.id", ondelete="CASCADE")
    )
    # Catalog exercises are retired with is_active, not deleted, so one that a
    # plan uses cannot be deleted (RESTRICT). Indexed for that check.
    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="RESTRICT"), index=True
    )
    exercise_order: Mapped[int]
    sets: Mapped[int]
    reps: Mapped[int]
    weight_kg: Mapped[float | None]
    rest_seconds: Mapped[int | None]
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workout_plan: Mapped["WorkoutPlan"] = relationship(back_populates="exercises")
