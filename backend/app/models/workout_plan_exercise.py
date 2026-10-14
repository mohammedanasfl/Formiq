from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.exercise import Exercise
    from app.models.workout_plan import WorkoutPlan


class WorkoutPlanExercise(Base):
    """An exercise prescribed in a workout plan: the target sets, reps (or
    duration), weight and rest, not the performed ones.

    Each belongs to a section of the workout: the warm-up, the main workout or
    the cool-down. The same exercise may appear more than once in a plan, at
    different positions; each position (exercise_order) is used once per plan,
    across the sections.
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
    # a PlanSection value (app.schemas.workout_plan), validated by the schemas;
    # the exercises of plans made before sections existed are MAIN_WORKOUT
    section: Mapped[str] = mapped_column(String(20), server_default="MAIN_WORKOUT")
    sets: Mapped[int]
    # Each set's target: reps, or a duration for a timed activity such as an
    # easy walk or a stretch held. Exactly one of them, checked by the schemas
    # and the services.
    reps: Mapped[int | None]
    duration_seconds: Mapped[int | None]
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
    # The catalog exercise, for its name, description and instructions: read,
    # never changed through the plan (viewonly). selectin: the exercises of
    # every plan exercise loaded together come in one extra query, however
    # the plan exercises were loaded, never one query each.
    exercise: Mapped["Exercise"] = relationship(viewonly=True, lazy="selectin")
