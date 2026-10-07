from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workout_session_exercise import WorkoutSessionExercise


class WorkoutSet(Base):
    """A set actually performed: the reps, weight and effort that happened,
    not the prescription (which stays in the workout plan).

    completed is false for a skipped or incomplete set.
    """

    __tablename__ = "workout_sets"
    # Its index, which starts with workout_session_exercise_id, also serves
    # loading an exercise's sets and deleting them with the exercise.
    __table_args__ = (UniqueConstraint("workout_session_exercise_id", "set_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    # deleted with their session exercise (CASCADE)
    workout_session_exercise_id: Mapped[int] = mapped_column(
        ForeignKey("workout_session_exercises.id", ondelete="CASCADE")
    )
    set_number: Mapped[int]
    reps: Mapped[int]
    weight_kg: Mapped[float | None]
    # rate of perceived exertion, 1 to 10, validated by the schemas
    rpe: Mapped[float | None]
    completed: Mapped[bool] = mapped_column(server_default=true())
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    workout_session_exercise: Mapped["WorkoutSessionExercise"] = relationship(
        back_populates="sets"
    )
