"""Rules shared by the workout session services: sessions, their exercises and sets."""

from app.models import WorkoutSession, WorkoutSessionExercise
from app.repositories import (
    WorkoutPlanExerciseRepository,
    WorkoutSessionExerciseRepository,
    WorkoutSessionRepository,
)
from app.schemas import WorkoutSessionStatus
from app.services.exceptions import (
    InvalidSessionStatusTransitionError,
    InvalidWorkoutSessionError,
    WorkoutSessionExerciseNotFoundError,
    WorkoutSessionNotEditableError,
    WorkoutSessionNotFoundError,
)

IN_PROGRESS = WorkoutSessionStatus.IN_PROGRESS
COMPLETED = WorkoutSessionStatus.COMPLETED
CANCELLED = WorkoutSessionStatus.CANCELLED

# The statuses that a session in each status can change to. A session runs
# until it is COMPLETED or CANCELLED, and both are final.
ALLOWED_STATUS_CHANGES = {
    IN_PROGRESS: {IN_PROGRESS, COMPLETED, CANCELLED},
    COMPLETED: {COMPLETED},
    CANCELLED: {CANCELLED},
}

# Fields that are NOT NULL in the tables. The update schemas accept null for
# every field, so an update must not set these to null.
REQUIRED_SESSION_FIELDS = frozenset({"status"})
REQUIRED_SESSION_EXERCISE_FIELDS = frozenset({"exercise_id", "exercise_order"})
REQUIRED_SET_FIELDS = frozenset({"set_number", "reps", "completed"})


def get_owned_session(
    sessions: WorkoutSessionRepository, user_id: int, session_id: int
) -> WorkoutSession:
    """The user's session. A session of another user is treated as missing."""
    workout_session = sessions.get_for_user(user_id, session_id)
    if workout_session is None:
        raise WorkoutSessionNotFoundError(f"user {user_id} has no workout session {session_id}")
    return workout_session


def get_session_exercise(
    session_exercises: WorkoutSessionExerciseRepository, session_id: int, session_exercise_id: int
) -> WorkoutSessionExercise:
    """The session's exercise. An exercise of another session is treated as missing."""
    session_exercise = session_exercises.get_for_session(session_id, session_exercise_id)
    if session_exercise is None:
        raise WorkoutSessionExerciseNotFoundError(
            f"workout session {session_id} has no exercise {session_exercise_id}"
        )
    return session_exercise


def check_in_progress(workout_session: WorkoutSession) -> None:
    """A COMPLETED or CANCELLED session is history: neither it nor its
    exercises and sets can be changed."""
    if workout_session.status != IN_PROGRESS:
        raise WorkoutSessionNotEditableError(
            f"workout session {workout_session.id} is {workout_session.status} "
            "and cannot be changed"
        )


def check_status_change(current: str, new: str) -> None:
    if new not in ALLOWED_STATUS_CHANGES[current]:
        raise InvalidSessionStatusTransitionError(
            f"a {current} workout session cannot become {new}"
        )


def check_completed_session(status: str, exercise_count: int) -> None:
    """A COMPLETED session has at least one exercise."""
    if status == COMPLETED and exercise_count == 0:
        raise InvalidWorkoutSessionError("a COMPLETED workout session needs at least one exercise")


def check_plan_exercise(
    plan_exercises: WorkoutPlanExerciseRepository,
    workout_session: WorkoutSession,
    plan_exercise_id: int | None,
) -> None:
    """A session exercise can only link an exercise of the session's own plan,
    which belongs to the same user. A session without a plan links none."""
    if plan_exercise_id is None:
        return
    plan_id = workout_session.workout_plan_id
    if plan_id is None:
        raise InvalidWorkoutSessionError(
            f"workout session {workout_session.id} has no workout plan, so it cannot "
            f"link plan exercise {plan_exercise_id}"
        )
    if plan_exercises.get_for_plan(plan_id, plan_exercise_id) is None:
        raise InvalidWorkoutSessionError(
            f"workout plan {plan_id} has no exercise {plan_exercise_id}"
        )


def check_no_null_required_fields(changes: dict, required_fields: frozenset[str]) -> None:
    null_fields = sorted(
        field for field, value in changes.items() if value is None and field in required_fields
    )
    if null_fields:
        raise InvalidWorkoutSessionError(
            f"these fields cannot be null: {', '.join(null_fields)}"
        )
