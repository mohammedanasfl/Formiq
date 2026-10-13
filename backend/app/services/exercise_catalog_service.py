from pathlib import Path

from sqlalchemy.orm import Session

from app.catalog.images import resolve_image
from app.models import Equipment, Exercise, MuscleGroup
from app.repositories import EquipmentRepository, ExerciseRepository, MuscleGroupRepository
from app.schemas import ExerciseFilters


class ExerciseCatalogService:
    """Read access to the exercise catalog: exercises, muscle groups and equipment.

    The catalog has no write operations yet, so there is no transaction to
    commit or roll back.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.exercises = ExerciseRepository(session)
        self.muscle_groups = MuscleGroupRepository(session)
        self.equipment = EquipmentRepository(session)

    def list_exercises(
        self, filters: ExerciseFilters, *, available_equipment_ids: list[int] | None = None
    ) -> list[Exercise]:
        """The exercises matching the filters, ordered by name; with
        available_equipment_ids, only those that need nothing else."""
        return self.exercises.find(
            available_equipment_ids=available_equipment_ids,
            difficulty=filters.difficulty,
            movement_pattern=filters.movement_pattern,
            use=filters.use,
            muscle_group_id=filters.muscle_group_id,
            equipment_id=filters.equipment_id,
            is_active=filters.is_active,
        )

    def get_exercise_by_id(self, exercise_id: int) -> Exercise | None:
        """The exercise, active or not: inactive exercises stay readable by id."""
        return self.exercises.get_by_id(exercise_id)

    def get_exercise_image(
        self, exercise_id: int, position: int, images_dir: Path
    ) -> Path | None:
        """The file of the exercise's image at this position (0 is the first),
        or None when the exercise has no such image or its file is missing.
        Only a stored path that resolves to a file inside images_dir is ever
        returned."""
        exercise = self.exercises.get_by_id(exercise_id)
        if exercise is None or not 0 <= position < len(exercise.image_paths):
            return None
        return resolve_image(images_dir, exercise.image_paths[position])

    def list_muscle_groups(self, is_active: bool) -> list[MuscleGroup]:
        return self.muscle_groups.find(is_active=is_active)

    def list_equipment(self, is_active: bool) -> list[Equipment]:
        return self.equipment.find(is_active=is_active)
