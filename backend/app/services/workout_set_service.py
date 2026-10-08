from sqlalchemy.orm import Session

from app.models import WorkoutSet
from app.repositories import (
    WorkoutSessionExerciseRepository,
    WorkoutSessionRepository,
    WorkoutSetRepository,
)
from app.schemas import WorkoutSetCreate, WorkoutSetUpdate
from app.services.exceptions import SetNumberTakenError, WorkoutSetNotFoundError
from app.services.workout_session_rules import (
    REQUIRED_SET_FIELDS,
    check_in_progress,
    check_no_null_required_fields,
    get_owned_session,
    get_session_exercise,
)


class WorkoutSetService:
    """Records, changes and removes the sets of an exercise in a user's
    IN_PROGRESS session."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.sessions = WorkoutSessionRepository(session)
        self.session_exercises = WorkoutSessionExerciseRepository(session)
        self.sets = WorkoutSetRepository(session)

    def add_set(
        self, user_id: int, session_id: int, session_exercise_id: int, set_data: WorkoutSetCreate
    ) -> WorkoutSet:
        try:
            workout_session = get_owned_session(self.sessions, user_id, session_id)
            session_exercise = get_session_exercise(
                self.session_exercises, workout_session.id, session_exercise_id
            )
            check_in_progress(workout_session)
            self.check_set_number_free(session_exercise.id, set_data.set_number)

            workout_set = self.sets.create(
                WorkoutSet(workout_session_exercise_id=session_exercise.id, **set_data.model_dump())
            )
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(workout_set)
        return workout_set

    def update_set(
        self,
        user_id: int,
        session_id: int,
        session_exercise_id: int,
        set_id: int,
        set_data: WorkoutSetUpdate,
    ) -> WorkoutSet:
        changes = set_data.model_dump(exclude_unset=True)
        try:
            workout_set = self.get_owned_set(user_id, session_id, session_exercise_id, set_id)
            check_no_null_required_fields(changes, REQUIRED_SET_FIELDS)
            if changes.get("set_number", workout_set.set_number) != workout_set.set_number:
                self.check_set_number_free(session_exercise_id, changes["set_number"])

            for field, value in changes.items():
                setattr(workout_set, field, value)
            self.sets.update(workout_set)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(workout_set)
        return workout_set

    def remove_set(
        self, user_id: int, session_id: int, session_exercise_id: int, set_id: int
    ) -> None:
        """Deletes the set. The other sets keep their set_number."""
        try:
            workout_set = self.get_owned_set(user_id, session_id, session_exercise_id, set_id)
            self.sets.delete(workout_set)
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def get_owned_set(
        self, user_id: int, session_id: int, session_exercise_id: int, set_id: int
    ) -> WorkoutSet:
        """The set, if it belongs to the session exercise of the user's session,
        and the session is still IN_PROGRESS."""
        workout_session = get_owned_session(self.sessions, user_id, session_id)
        session_exercise = get_session_exercise(
            self.session_exercises, workout_session.id, session_exercise_id
        )
        workout_set = self.sets.get_for_session_exercise(session_exercise.id, set_id)
        if workout_set is None:
            raise WorkoutSetNotFoundError(
                f"session exercise {session_exercise.id} has no set {set_id}"
            )
        check_in_progress(workout_session)
        return workout_set

    def check_set_number_free(self, session_exercise_id: int, set_number: int) -> None:
        if self.sets.get_by_set_number(session_exercise_id, set_number) is not None:
            raise SetNumberTakenError(
                f"session exercise {session_exercise_id} already has a set with set_number "
                f"{set_number}"
            )
