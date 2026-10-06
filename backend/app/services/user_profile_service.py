from sqlalchemy.orm import Session

from app.models import UserProfile
from app.repositories import UserProfileRepository, UserRepository
from app.schemas import UserProfileCreate, UserProfileUpdate
from app.services.exceptions import (
    InvalidProfileUpdateError,
    UserNotFoundError,
    UserProfileAlreadyExistsError,
    UserProfileNotFoundError,
)

# Profile fields that are NOT NULL in the user_profiles table. UserProfileUpdate
# accepts null for every field, so an update must not set these to null.
REQUIRED_PROFILE_FIELDS = frozenset(
    {
        "first_name",
        "age",
        "height_cm",
        "weight_kg",
        "gender",
        "fitness_experience",
        "goal",
        "training_frequency_per_week",
        "training_location",
        "activity_level",
        "sleep_hours",
    }
)


class UserProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.profiles = UserProfileRepository(session)

    def create_profile(self, user_id: int, profile_data: UserProfileCreate) -> UserProfile:
        try:
            if self.users.get_by_id(user_id) is None:
                raise UserNotFoundError(f"user {user_id} does not exist")
            if self.profiles.get_by_user_id(user_id) is not None:
                raise UserProfileAlreadyExistsError(f"user {user_id} already has a profile")

            profile = self.profiles.create(
                UserProfile(user_id=user_id, **profile_data.model_dump())
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(profile)
        return profile

    def get_profile_by_user_id(self, user_id: int) -> UserProfile | None:
        return self.profiles.get_by_user_id(user_id)

    def update_profile(self, user_id: int, profile_data: UserProfileUpdate) -> UserProfile:
        changes = profile_data.model_dump(exclude_unset=True)
        try:
            profile = self.profiles.get_by_user_id(user_id)
            if profile is None:
                raise UserProfileNotFoundError(f"user {user_id} has no profile")

            null_required_fields = sorted(
                field
                for field, value in changes.items()
                if value is None and field in REQUIRED_PROFILE_FIELDS
            )
            if null_required_fields:
                raise InvalidProfileUpdateError(
                    f"these fields cannot be null: {', '.join(null_required_fields)}"
                )

            for field, value in changes.items():
                setattr(profile, field, value)
            self.profiles.update(profile)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(profile)
        return profile
