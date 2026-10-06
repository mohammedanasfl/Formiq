from sqlalchemy import exists, select
from sqlalchemy.orm import Session, selectinload

from app.models import Exercise, ExerciseMuscle, exercise_equipment

# Loads the muscles (with their muscle groups) and the equipment of all the
# exercises a query returns in one extra query each, instead of one per
# exercise. selectinload keeps the two collections out of the exercise query,
# where joining both would multiply the rows; the muscle group is a
# many-to-one, so joining it into the muscles query adds no rows.
LOAD_MUSCLES_AND_EQUIPMENT = (
    selectinload(Exercise.muscles).joinedload(ExerciseMuscle.muscle_group, innerjoin=True),
    selectinload(Exercise.equipment),
)


class ExerciseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_id(self, exercise_id: int) -> Exercise | None:
        return self.session.get(Exercise, exercise_id, options=LOAD_MUSCLES_AND_EQUIPMENT)

    def find(
        self,
        *,
        difficulty: str | None = None,
        movement_pattern: str | None = None,
        muscle_group_id: int | None = None,
        equipment_id: int | None = None,
        is_active: bool | None = None,
    ) -> list[Exercise]:
        """Exercises matching every value that is not None, ordered by name."""
        query = select(Exercise).options(*LOAD_MUSCLES_AND_EQUIPMENT).order_by(Exercise.name)
        if difficulty is not None:
            query = query.where(Exercise.difficulty == difficulty)
        if movement_pattern is not None:
            query = query.where(Exercise.movement_pattern == movement_pattern)
        if muscle_group_id is not None:
            # as a primary or secondary muscle
            query = query.where(
                exists().where(
                    ExerciseMuscle.exercise_id == Exercise.id,
                    ExerciseMuscle.muscle_group_id == muscle_group_id,
                )
            )
        if equipment_id is not None:
            query = query.where(
                exists().where(
                    exercise_equipment.c.exercise_id == Exercise.id,
                    exercise_equipment.c.equipment_id == equipment_id,
                )
            )
        if is_active is not None:
            query = query.where(Exercise.is_active == is_active)
        return list(self.session.scalars(query))
