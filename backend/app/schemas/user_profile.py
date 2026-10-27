from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
    StringConstraints,
    model_validator,
)

# Text limited to the length of the matching user_profiles column.
Name = Annotated[str, StringConstraints(min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=50)]
# Catalog equipment ids, as GET /equipment lists them. The catalog is a few dozen pieces: a
# longer list can only repeat ids, which count once.
EquipmentIds = Annotated[list[PositiveInt], Field(max_length=100)]

NO_EQUIPMENT_WITH_EQUIPMENT = "no_equipment cannot be true while equipment_ids lists equipment"


class UserProfileCreate(BaseModel):
    first_name: Name
    last_name: Name | None = None
    age: PositiveInt
    height_cm: PositiveFloat
    weight_kg: PositiveFloat
    gender: ShortText
    fitness_experience: ShortText
    goal: ShortText
    target_weight_kg: PositiveFloat | None = None
    goal_period_weeks: PositiveInt | None = None
    training_frequency_per_week: NonNegativeInt
    training_location: ShortText
    activity_level: ShortText
    sleep_hours: NonNegativeFloat
    dietary_preference: ShortText | None = None
    # The catalog equipment the user has (each id once: a repeat is ignored). No ids and
    # no_equipment false says nothing about it, as a profile made before equipment was kept.
    equipment_ids: EquipmentIds = Field(default_factory=list)
    # The user has no equipment: bodyweight only. Never with equipment_ids.
    no_equipment: bool = False

    @model_validator(mode="after")
    def _none_or_some_equipment(self) -> "UserProfileCreate":
        if self.no_equipment and self.equipment_ids:
            raise ValueError(NO_EQUIPMENT_WITH_EQUIPMENT)
        return self


class UserProfileUpdate(BaseModel):
    first_name: Name | None = None
    last_name: Name | None = None
    age: PositiveInt | None = None
    height_cm: PositiveFloat | None = None
    weight_kg: PositiveFloat | None = None
    gender: ShortText | None = None
    fitness_experience: ShortText | None = None
    goal: ShortText | None = None
    target_weight_kg: PositiveFloat | None = None
    goal_period_weeks: PositiveInt | None = None
    training_frequency_per_week: NonNegativeInt | None = None
    training_location: ShortText | None = None
    activity_level: ShortText | None = None
    sleep_hours: NonNegativeFloat | None = None
    dietary_preference: ShortText | None = None
    # A list replaces the user's equipment (not a null: that is refused by the service). A list
    # alone clears no_equipment; no_equipment true alone clears the list.
    equipment_ids: EquipmentIds | None = None
    no_equipment: bool | None = None

    @model_validator(mode="after")
    def _none_or_some_equipment(self) -> "UserProfileUpdate":
        if self.no_equipment and self.equipment_ids:
            raise ValueError(NO_EQUIPMENT_WITH_EQUIPMENT)
        return self


class ProfileEquipmentResponse(BaseModel):
    """A piece of catalog equipment the user has."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class UserProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    first_name: str
    last_name: str | None
    age: int
    height_cm: float
    weight_kg: float
    gender: str
    fitness_experience: str
    goal: str
    target_weight_kg: float | None
    goal_period_weeks: int | None
    training_frequency_per_week: int
    training_location: str
    activity_level: str
    sleep_hours: float
    dietary_preference: str | None
    # The equipment the user has, as the catalog names it, each with its id for the id lists the
    # request takes. no_equipment: bodyweight only; with none listed either, the user never said.
    no_equipment: bool
    equipment: list[ProfileEquipmentResponse]
    created_at: datetime
    updated_at: datetime
