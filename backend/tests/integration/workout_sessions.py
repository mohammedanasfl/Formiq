"""Helpers for workout session integration tests."""

from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.models import User, WorkoutSession, WorkoutSessionExercise, WorkoutSet
from tests.integration.workout_plans import columns


def add_session(
    session: Session,
    user: User,
    *,
    exercises: Sequence[tuple[int, Sequence[int]]] = (),
    status: str = "IN_PROGRESS",
    **fields,
) -> WorkoutSession:
    """A session of the user, flushed only.

    exercises are (exercise_id, reps of each set) pairs, placed at
    exercise_order 1, 2, ... with sets numbered 1, 2, ...
    """
    workout_session = WorkoutSession(
        user_id=user.id,
        status=status,
        exercises=[
            WorkoutSessionExercise(
                exercise_id=exercise_id,
                exercise_order=order,
                sets=[
                    WorkoutSet(set_number=number, reps=reps)
                    for number, reps in enumerate(set_reps, start=1)
                ],
            )
            for order, (exercise_id, set_reps) in enumerate(exercises, start=1)
        ],
        **fields,
    )
    session.add(workout_session)
    session.flush()
    return workout_session


def stored_session(engine, session_id: int) -> dict | None:
    """The session, its exercises and their sets as committed in the database, or None."""
    with Session(engine) as session:
        workout_session = session.get(WorkoutSession, session_id)
        if workout_session is None:
            return None
        return {
            **columns(workout_session),
            "exercises": [
                {**columns(item), "sets": [columns(workout_set) for workout_set in item.sets]}
                for item in workout_session.exercises
            ],
        }
