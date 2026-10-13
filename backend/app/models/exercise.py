from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, String, Text, UniqueConstraint, func, text, true
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.equipment import Equipment
    from app.models.exercise_muscle import ExerciseMuscle


class Exercise(Base):
    """A reusable exercise definition in the catalog, not tied to any user.

    An exercise is Formiq's own (source FORMIQ), or imported from an upstream
    dataset (app.catalog), which keeps the upstream record as it was
    (source_record), its upstream id (source_id, never Formiq's id) and the
    upstream version it came from. The muscles and equipment are the record's,
    mapped to Formiq's catalog; uses is Formiq's own judgement of the workout
    sections it suits.
    """

    __tablename__ = "exercises"
    # an upstream record is imported once; Formiq's own exercises have no source_id
    __table_args__ = (UniqueConstraint("source", "source_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # Difficulty and MovementPattern values (app.schemas.exercise), validated
    # by the schemas. movement_pattern is null when Formiq has not classified it.
    difficulty: Mapped[str] = mapped_column(String(20))
    movement_pattern: Mapped[str | None] = mapped_column(String(30))
    # WorkoutSection values: the sections Formiq judges the exercise suitable
    # for, in the order WARM_UP, MAIN_WORKOUT, COOL_DOWN; empty: none yet
    uses: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)), server_default=text("'{}'::varchar[]")
    )
    # The images to show, in order, as paths relative to the exercise images
    # directory (settings.exercise_images_dir). Only paths whose file existed
    # when they were stored; the API serves them by position, never by path.
    image_paths: Mapped[list[str]] = mapped_column(
        ARRAY(String(255)), server_default=text("'{}'::varchar[]")
    )
    # an ExerciseSource value
    source: Mapped[str] = mapped_column(String(30), server_default="FORMIQ")
    source_id: Mapped[str | None] = mapped_column(String(100))
    source_version: Mapped[str | None] = mapped_column(String(64))
    # the upstream record, every field as it was; null for Formiq's own
    source_record: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
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

    @property
    def instructions(self) -> list[str]:
        """The upstream record's steps, in order and unchanged; none for
        Formiq's own exercises, which have a description instead."""
        steps = (self.source_record or {}).get("instructions")
        return list(steps) if isinstance(steps, list) else []

    @property
    def category(self) -> str | None:
        """The upstream record's category, unchanged; None for Formiq's own."""
        category = (self.source_record or {}).get("category")
        return category if isinstance(category, str) else None
