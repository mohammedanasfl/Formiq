from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workout_plan_exercise import WorkoutPlanExercise


class WorkoutPlan(Base):
    """A workout planned for a user: what to do, not what was done."""

    __tablename__ = "workout_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    # A user with workout plans cannot be deleted (RESTRICT): the plans must not
    # disappear silently. Indexed for listing a user's plans.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    description: Mapped[str | None] = mapped_column(Text)
    # a WorkoutPlanStatus value (app.schemas.workout_plan), validated by the schemas
    status: Mapped[str] = mapped_column(String(20))
    scheduled_date: Mapped[date | None]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # passive_deletes: the database deletes the plan's exercises with the plan.
    exercises: Mapped[list["WorkoutPlanExercise"]] = relationship(
        back_populates="workout_plan",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="WorkoutPlanExercise.exercise_order",
    )
