from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="profile")
