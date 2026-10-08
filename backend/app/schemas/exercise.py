from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AliasPath, BaseModel, ConfigDict, Field

# Catalog IDs are PostgreSQL integer columns: filter values outside that range
# would fail in the database, and IDs below 1 are never assigned.
CatalogId = Annotated[int, Field(ge=1, le=2_147_483_647)]


class Difficulty(StrEnum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class MovementPattern(StrEnum):
    HORIZONTAL_PUSH = "HORIZONTAL_PUSH"
    HORIZONTAL_PULL = "HORIZONTAL_PULL"
    VERTICAL_PUSH = "VERTICAL_PUSH"
    VERTICAL_PULL = "VERTICAL_PULL"
    SQUAT = "SQUAT"
    HINGE = "HINGE"
    LUNGE = "LUNGE"
    CARRY = "CARRY"
    ROTATION = "ROTATION"
    ISOLATION = "ISOLATION"


class MuscleRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class ExerciseFilters(BaseModel):
    """Filters for listing exercises. An exercise must match all of them."""

    difficulty: Difficulty | None = None
    movement_pattern: MovementPattern | None = None
    # the exercise trains this muscle group, as a primary or secondary muscle
    muscle_group_id: CatalogId | None = None
    # the exercise needs this equipment
    equipment_id: CatalogId | None = None
    is_active: bool = True


class ExerciseMuscleResponse(BaseModel):
    """A muscle group that the exercise trains, and its role in the exercise."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(validation_alias=AliasPath("muscle_group", "id"))
    name: str = Field(validation_alias=AliasPath("muscle_group", "name"))
    role: MuscleRole


class ExerciseEquipmentResponse(BaseModel):
    """A piece of equipment that the exercise needs."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class ExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    difficulty: Difficulty
    movement_pattern: MovementPattern
    # primary muscles first; an empty equipment list means no equipment is needed
    muscles: list[ExerciseMuscleResponse]
    equipment: list[ExerciseEquipmentResponse]
    is_active: bool
    created_at: datetime
    updated_at: datetime
