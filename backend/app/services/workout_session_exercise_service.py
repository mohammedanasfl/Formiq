from sqlalchemy.orm import Session

from app.models import WorkoutSessionExercise
from app.repositories import (
    ExerciseRepository,
    WorkoutPlanExerciseRepository,
    WorkoutSessionExerciseRepository,
    WorkoutSessionRepository,
)
from app.schemas import WorkoutSessionExerciseCreate, WorkoutSessionExerciseUpdate
from app.services.exceptions import SessionExerciseOrderTakenError
from app.services.workout_plan_rules import check_exercise_available
from app.services.workout_session_rules import (
    REQUIRED_SESSION_EXERCISE_FIELDS,
    check_in_progress,
    check_no_null_required_fields,
    check_plan_exercise,
    get_owned_session,
    get_session_exercise,
)


class WorkoutSessionExerciseService:
    """Adds, changes and removes the exercises of a user's IN_PROGRESS session."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.sessions = WorkoutSessionRepository(session)
        self.session_exercises = WorkoutSessionExerciseRepository(session)
        self.plan_exercises = WorkoutPlanExerciseRepository(session)
        self.exercises = ExerciseRepository(session)

    def add_exercise(
        self, user_id: int, session_id: int, exercise_data: WorkoutSessionExerciseCreate
    ) -> WorkoutSessionExercise:
        try:
            workout_session = get_owned_session(self.sessions, user_id, session_id)
            check_in_progress(workout_session)
            check_exercise_available(self.exercises, exercise_data.exercise_id)
            check_plan_exercise(
                self.plan_exercises, workout_session, exercise_data.plan_exercise_id
            )
            self.check_order_free(workout_session.id, exercise_data.exercise_order)

            session_exercise = self.session_exercises.create(
                WorkoutSessionExercise(
                    workout_session_id=workout_session.id, **exercise_data.model_dump()
                )
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(session_exercise)
        return session_exercise

    def update_exercise(
        self,
        user_id: int,
        session_id: int,
        session_exercise_id: int,
        exercise_data: WorkoutSessionExerciseUpdate,
    ) -> WorkoutSessionExercise:
        changes = exercise_data.model_dump(exclude_unset=True)
        try:
            workout_session = get_owned_session(self.sessions, user_id, session_id)
            session_exercise = get_session_exercise(
                self.session_exercises, workout_session.id, session_exercise_id
            )
            check_in_progress(workout_session)
            check_no_null_required_fields(changes, REQUIRED_SESSION_EXERCISE_FIELDS)
            if (
                changes.get("exercise_id", session_exercise.exercise_id)
                != session_exercise.exercise_id
            ):
                check_exercise_available(self.exercises, changes["exercise_id"])
            if (
                changes.get("plan_exercise_id", session_exercise.plan_exercise_id)
                != session_exercise.plan_exercise_id
            ):
                check_plan_exercise(
                    self.plan_exercises, workout_session, changes["plan_exercise_id"]
                )
            if (
                changes.get("exercise_order", session_exercise.exercise_order)
                != session_exercise.exercise_order
            ):
                self.check_order_free(workout_session.id, changes["exercise_order"])

            for field, value in changes.items():
                setattr(session_exercise, field, value)
            self.session_exercises.update(session_exercise)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(session_exercise)
        return session_exercise

    def remove_exercise(self, user_id: int, session_id: int, session_exercise_id: int) -> None:
        """Deletes the exercise and its sets. The other exercises keep their order."""
        try:
            workout_session = get_owned_session(self.sessions, user_id, session_id)
            session_exercise = get_session_exercise(
                self.session_exercises, workout_session.id, session_exercise_id
            )
            check_in_progress(workout_session)

            self.session_exercises.delete(session_exercise)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def check_order_free(self, session_id: int, exercise_order: int) -> None:
        if self.session_exercises.get_by_order(session_id, exercise_order) is not None:
            raise SessionExerciseOrderTakenError(
                f"workout session {session_id} already has an exercise at exercise_order "
                f"{exercise_order}"
            )
