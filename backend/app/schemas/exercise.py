from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any

from pydantic import AliasPath, BaseModel, ConfigDict, Field, ValidationInfo, field_validator

# Catalog IDs are PostgreSQL integer columns: filter values outside that range
# would fail in the database, and IDs below 1 are never assigned.
CatalogId = Annotated[int, Field(ge=1, le=2_147_483_647)]


class WorkoutSection(StrEnum):
    """The parts of a workout: the preparation before the training, the
    training itself, and the recovery after it.

    An exercise's uses are the sections Formiq judges it suitable for (one or
    more); a planned exercise's section is the one it is in. This is Formiq's
    own classification, kept apart from an imported exercise's upstream
    category."""

    WARM_UP = "WARM_UP"
    MAIN_WORKOUT = "MAIN_WORKOUT"
    COOL_DOWN = "COOL_DOWN"


class ExerciseSource(StrEnum):
    """Where a catalog exercise comes from: written by Formiq, or imported
    from an upstream dataset (app.catalog)."""

    FORMIQ = "FORMIQ"
    FREE_EXERCISE_DB = "FREE_EXERCISE_DB"


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
    # The warm-up and cool-down activities: dynamic joint and muscle drills,
    # static stretches, and light cardio such as an easy walk.
    MOBILITY = "MOBILITY"
    STRETCH = "STRETCH"
    CARDIO = "CARDIO"


class MuscleRole(StrEnum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class ExerciseFilters(BaseModel):
    """Filters for listing exercises. An exercise must match all of them."""

    difficulty: Difficulty | None = None
    movement_pattern: MovementPattern | None = None
    # Formiq judges the exercise suitable for this section of a workout
    use: WorkoutSection | None = None
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


class ExerciseImageResponse(BaseModel):
    """An image of the exercise: fetch it from url, a path on this API
    (GET /exercises/{exercise_id}/images/{position})."""

    position: int
    url: str


def image_url(exercise_id: int, position: int) -> str:
    return f"/exercises/{exercise_id}/images/{position}"


class ExerciseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    # Formiq's own short description; null for an imported exercise, whose
    # upstream record has none
    description: str | None
    # the upstream record's steps, in order and unchanged; empty for Formiq's own
    instructions: list[str]
    difficulty: Difficulty
    # Formiq's movement pattern; null when Formiq has not classified it (most
    # imported exercises)
    movement_pattern: MovementPattern | None
    # the upstream record's category (such as "strength" or "stretching"),
    # unchanged; null for Formiq's own
    category: str | None
    # the workout sections Formiq judges it suitable for; empty: none yet
    uses: list[WorkoutSection]
    # primary muscles first; an empty equipment list means no equipment is needed
    muscles: list[ExerciseMuscleResponse]
    equipment: list[ExerciseEquipmentResponse]
    # in order; an empty list means the exercise has no image to show
    images: list[ExerciseImageResponse] = Field(validation_alias="image_paths")
    source: ExerciseSource
    # the upstream record's own id (never Formiq's id) and the upstream version
    # (a git commit) it was imported from; null for Formiq's own exercises
    source_id: str | None
    source_version: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator("images", mode="before")
    @classmethod
    def image_urls(cls, paths: Any, info: ValidationInfo) -> Any:
        """The stored paths become the API's image URLs: a client never sees
        where an image is kept."""
        if not isinstance(paths, list) or "id" not in info.data:
            return paths
        exercise_id = info.data["id"]
        return [
            {"position": position, "url": image_url(exercise_id, position)}
            for position in range(len(paths))
        ]
