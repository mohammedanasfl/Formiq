from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.equipment import Equipment
    from app.models.exercise_muscle import ExerciseMuscle


class Exercise(Base):
    """A reusable exercise definition in the catalog, not tied to any user."""

    __tablename__ = "exercises"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Difficulty and MovementPattern values (app.schemas.exercise), validated
    # by the schemas
    difficulty: Mapped[str] = mapped_column(String(20))
    movement_pattern: Mapped[str] = mapped_column(String(30))
    is_active: Mapped[bool] = mapped_column(server_default=true())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # PRIMARY sorts before SECONDARY, so the primary muscles come first.
    # passive_deletes: the database deletes the links with the exercise.
    muscles: Mapped[list["ExerciseMuscle"]] = relationship(
        back_populates="exercise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="[ExerciseMuscle.role, ExerciseMuscle.muscle_group_id]",
    )
    equipment: Mapped[list["Equipment"]] = relationship(
        secondary="exercise_equipment", order_by="Equipment.id", passive_deletes=True
    )
