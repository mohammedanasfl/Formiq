from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import WorkoutSessionExercise


class WorkoutSessionExerciseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, session_exercise: WorkoutSessionExercise) -> WorkoutSessionExercise:
        self.session.add(session_exercise)
        self.session.flush()
        return session_exercise

    def get_for_session(
        self, workout_session_id: int, session_exercise_id: int
    ) -> WorkoutSessionExercise | None:
        """The session exercise, or None if it does not exist or belongs to another session."""
        return self.session.scalars(
            select(WorkoutSessionExercise).where(
                WorkoutSessionExercise.id == session_exercise_id,
                WorkoutSessionExercise.workout_session_id == workout_session_id,
            )
        ).one_or_none()

    def get_by_order(
        self, workout_session_id: int, exercise_order: int
    ) -> WorkoutSessionExercise | None:
        return self.session.scalars(
            select(WorkoutSessionExercise).where(
                WorkoutSessionExercise.workout_session_id == workout_session_id,
                WorkoutSessionExercise.exercise_order == exercise_order,
            )
        ).one_or_none()

    def update(self, session_exercise: WorkoutSessionExercise) -> WorkoutSessionExercise:
        self.session.add(session_exercise)
        self.session.flush()
        return session_exercise

    def delete(self, session_exercise: WorkoutSessionExercise) -> None:
        self.session.delete(session_exercise)
        self.session.flush()
