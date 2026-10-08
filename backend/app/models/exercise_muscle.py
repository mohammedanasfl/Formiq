from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.exercise import Exercise
    from app.models.muscle_group import MuscleGroup


class ExerciseMuscle(Base):
    """A muscle group that an exercise trains, as a PRIMARY or SECONDARY muscle.

    The rows belong to the exercise: deleting the exercise deletes them, while a
    muscle group that an exercise uses cannot be deleted (deactivate it instead).
    """

    __tablename__ = "exercise_muscles"

    exercise_id: Mapped[int] = mapped_column(
        ForeignKey("exercises.id", ondelete="CASCADE"), primary_key=True
    )
    # indexed for finding the exercises that train a muscle group; the primary
    # key index starts with exercise_id
    muscle_group_id: Mapped[int] = mapped_column(
        ForeignKey("muscle_groups.id", ondelete="RESTRICT"), primary_key=True, index=True
    )
    # a MuscleRole value (app.schemas.exercise), validated by the schemas
    role: Mapped[str] = mapped_column(String(20))

    exercise: Mapped["Exercise"] = relationship(back_populates="muscles")
    muscle_group: Mapped["MuscleGroup"] = relationship()
