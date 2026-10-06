from sqlalchemy.orm import Session

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

    def list_exercises(self, filters: ExerciseFilters) -> list[Exercise]:
        return self.exercises.find(
            difficulty=filters.difficulty,
            movement_pattern=filters.movement_pattern,
            muscle_group_id=filters.muscle_group_id,
            equipment_id=filters.equipment_id,
            is_active=filters.is_active,
        )

    def get_exercise_by_id(self, exercise_id: int) -> Exercise | None:
        """The exercise, active or not: inactive exercises stay readable by id."""
        return self.exercises.get_by_id(exercise_id)

    def list_muscle_groups(self, is_active: bool) -> list[MuscleGroup]:
        return self.muscle_groups.find(is_active=is_active)

    def list_equipment(self, is_active: bool) -> list[Equipment]:
        return self.equipment.find(is_active=is_active)
