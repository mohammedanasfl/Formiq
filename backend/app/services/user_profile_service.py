from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Equipment, UserProfile
from app.repositories import EquipmentRepository, UserProfileRepository, UserRepository
from app.schemas import UserProfileCreate, UserProfileUpdate
from app.services.exceptions import (
    InvalidEquipmentError,
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
        "no_equipment",
    }
)

# What an update may not set to null: the required fields, and the equipment list, which
# is replaced by a list and never by nothing.
NOT_NULL_UPDATE_FIELDS = REQUIRED_PROFILE_FIELDS | {"equipment_ids"}


@dataclass(frozen=True)
class SavedEquipment:
    """What a profile says about its user's equipment, by the catalog's names:
    the active equipment they chose, or that they chose none (bodyweight only)."""

    names: tuple[str, ...]
    none: bool


class UserProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.profiles = UserProfileRepository(session)
        self.equipment = EquipmentRepository(session)

    def create_profile(self, user_id: int, profile_data: UserProfileCreate) -> UserProfile:
        try:
            if self.users.get_by_id(user_id) is None:
                raise UserNotFoundError(f"user {user_id} does not exist")
            if self.profiles.get_by_user_id(user_id) is not None:
                raise UserProfileAlreadyExistsError(f"user {user_id} already has a profile")

            equipment = self._active_equipment(profile_data.equipment_ids)
            profile = self.profiles.create(
                UserProfile(
                    user_id=user_id,
                    **profile_data.model_dump(exclude={"equipment_ids"}),
                    equipment=equipment,
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(profile)
        return profile

    def get_profile_by_user_id(self, user_id: int) -> UserProfile | None:
        return self.profiles.get_by_user_id(user_id)

    def get_saved_equipment(self, user_id: int) -> SavedEquipment | None:
        """What the user's profile says about their equipment, for the coach. None
        when they have no profile or it never said (it lists none and does not say
        they have none; or what it lists has since been retired from the catalog):
        the coach then assumes nothing about their equipment."""
        profile = self.profiles.get_by_user_id(user_id)
        if profile is None:
            return None
        names = tuple(item.name for item in profile.equipment if item.is_active)
        if not profile.no_equipment and not names:
            return None
        return SavedEquipment(names=names, none=profile.no_equipment)

    def update_profile(self, user_id: int, profile_data: UserProfileUpdate) -> UserProfile:
        changes = profile_data.model_dump(exclude_unset=True)
        try:
            profile = self.profiles.get_by_user_id(user_id)
            if profile is None:
                raise UserProfileNotFoundError(f"user {user_id} has no profile")

            null_required_fields = sorted(
                field
                for field, value in changes.items()
                if value is None and field in NOT_NULL_UPDATE_FIELDS
            )
            if null_required_fields:
                raise InvalidProfileUpdateError(
                    f"these fields cannot be null: {', '.join(null_required_fields)}"
                )

            equipment_ids = changes.pop("equipment_ids", None)
            if equipment_ids is not None:
                # a list replaces the user's equipment; one that names some says they have
                # some, unless the same request says otherwise
                if equipment_ids:
                    changes.setdefault("no_equipment", False)
                self._replace_equipment(profile, self._active_equipment(equipment_ids))
            elif changes.get("no_equipment"):
                # having none leaves nothing listed
                self._replace_equipment(profile, [])

            for field, value in changes.items():
                setattr(profile, field, value)
            self.profiles.update(profile)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(profile)
        return profile

    def _active_equipment(self, equipment_ids: Sequence[int]) -> list[Equipment]:
        """The active catalog equipment these ids name, each once, in the order
        given. An id the catalog does not have, or one that is retired, is an
        InvalidEquipmentError that names it: nothing is saved with it."""
        wanted = list(dict.fromkeys(equipment_ids))
        found = {item.id: item for item in self.equipment.get_by_ids(wanted)}
        unknown = [item_id for item_id in wanted if item_id not in found]
        retired = [item_id for item_id in wanted if item_id in found and not found[item_id].is_active]
        problems = []
        if unknown:
            problems.append(f"equipment {', '.join(map(str, unknown))} is not in the catalog")
        if retired:
            problems.append(
                f"equipment {', '.join(map(str, retired))} is retired (is_active is false), "
                "so it cannot be chosen"
            )
        if problems:
            raise InvalidEquipmentError("; ".join(problems))
        return [found[item_id] for item_id in wanted]

    @staticmethod
    def _replace_equipment(profile: UserProfile, equipment: list[Equipment]) -> None:
        """The profile's equipment becomes exactly this: the association rows
        that are no longer wanted go and the new ones are added, never twice."""
        if {item.id for item in profile.equipment} == {item.id for item in equipment}:
            return
        profile.equipment = equipment
        # a change to the list alone updates no column of the row
        profile.updated_at = func.now()
