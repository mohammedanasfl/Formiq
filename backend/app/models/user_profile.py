from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, false, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.equipment import Equipment
    from app.models.user import User


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    age: Mapped[int]
    height_cm: Mapped[float]
    weight_kg: Mapped[float]
    gender: Mapped[str] = mapped_column(String(50))
    fitness_experience: Mapped[str] = mapped_column(String(50))
    goal: Mapped[str] = mapped_column(String(50))
    target_weight_kg: Mapped[float | None]
    goal_period_weeks: Mapped[int | None]
    training_frequency_per_week: Mapped[int]
    training_location: Mapped[str] = mapped_column(String(50))
    activity_level: Mapped[str] = mapped_column(String(50))
    sleep_hours: Mapped[float]
    dietary_preference: Mapped[str | None] = mapped_column(String(50))
    # The user said they have no equipment (bodyweight only). With no equipment rows
    # either, they never said: the profile does not know, which is not "none".
    no_equipment: Mapped[bool] = mapped_column(server_default=false())
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")
    # The catalog equipment the user has, by name. Always loaded with the profile: the
    # profile is read for its response and by the coach, never without it.
    equipment: Mapped[list["Equipment"]] = relationship(
        secondary="user_profile_equipment",
        order_by="Equipment.name",
        passive_deletes=True,
        lazy="selectin",
    )
