from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutSet


class WorkoutSetRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, workout_set: WorkoutSet) -> WorkoutSet:
        self.session.add(workout_set)
        self.session.flush()
        return workout_set

    def get_for_session_exercise(self, session_exercise_id: int, set_id: int) -> WorkoutSet | None:
        """The set, or None if it does not exist or belongs to another session exercise."""
        return self.session.scalars(
            select(WorkoutSet).where(
                WorkoutSet.id == set_id,
                WorkoutSet.workout_session_exercise_id == session_exercise_id,
            )
        ).one_or_none()

    def get_by_set_number(self, session_exercise_id: int, set_number: int) -> WorkoutSet | None:
        return self.session.scalars(
            select(WorkoutSet).where(
                WorkoutSet.workout_session_exercise_id == session_exercise_id,
                WorkoutSet.set_number == set_number,
            )
        ).one_or_none()

    def update(self, workout_set: WorkoutSet) -> WorkoutSet:
        self.session.add(workout_set)
        self.session.flush()
        return workout_set

    def delete(self, workout_set: WorkoutSet) -> None:
        self.session.delete(workout_set)
        self.session.flush()
