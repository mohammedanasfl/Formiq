"""Integration tests for the workout session, session exercise and set repositories.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.models import WorkoutSession, WorkoutSessionExercise, WorkoutSet
from app.repositories import (
    WorkoutSessionExerciseRepository,
    WorkoutSessionRepository,
    WorkoutSetRepository,
)
from tests.integration.workout_plans import add_user
from tests.integration.workout_sessions import add_session


@pytest.fixture
def sessions(db_session):
    return WorkoutSessionRepository(db_session)


@pytest.fixture
def session_exercises(db_session):
    return WorkoutSessionExerciseRepository(db_session)


@pytest.fixture
def sets(db_session):
    return WorkoutSetRepository(db_session)


@pytest.fixture
def user(db_session):
    return add_user(db_session, "session-repository@example.com")


@pytest.fixture
def other_user(db_session):
    return add_user(db_session, "session-repository-other@example.com")


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


@contextmanager
def count_queries(engine):
    """Collects the SQL statements sent to the database inside the block."""
    statements = []

    def collect(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", collect)


def started(day):
    return datetime(2026, 10, day, 7, 0, tzinfo=timezone.utc)


# WorkoutSessionRepository


def test_create_flushes_the_session_with_its_exercises_and_sets(
    sessions, db_session, user, bench_press
):
    workout_session = sessions.create(
        WorkoutSession(
            user_id=user.id,
            status="IN_PROGRESS",
            exercises=[
                WorkoutSessionExercise(
                    exercise_id=bench_press,
                    exercise_order=1,
                    sets=[WorkoutSet(set_number=1, reps=8, weight_kg=50.0, rpe=8.0)],
                )
            ],
        )
    )

    assert workout_session.id is not None
    assert workout_session.exercises[0].sets[0].id is not None
    assert not db_session.new  # flushed to the database


def test_get_by_id_returns_the_session_with_exercises_and_sets(
    sessions, db_session, user, bench_press, squat
):
    session_id = add_session(db_session, user, exercises=[(bench_press, [8, 6]), (squat, [5])]).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    workout_session = sessions.get_by_id(session_id)

    assert [
        (item.exercise_id, [s.reps for s in item.sets]) for item in workout_session.exercises
    ] == [(bench_press, [8, 6]), (squat, [5])]
    assert sessions.get_by_id(-1) is None


def test_get_for_user_returns_only_the_users_session(sessions, db_session, user, other_user):
    session_id = add_session(db_session, user).id
    db_session.expunge_all()

    assert sessions.get_for_user(user.id, session_id).id == session_id
    assert sessions.get_for_user(other_user.id, session_id) is None
    assert sessions.get_for_user(user.id, -1) is None


def test_find_by_user_returns_only_the_users_sessions_latest_first(
    sessions, db_session, user, other_user
):
    older = add_session(db_session, user, started_at=started(1))
    newer = add_session(db_session, user, started_at=started(3))
    middle = add_session(db_session, user, started_at=started(2))
    add_session(db_session, other_user, started_at=started(4))

    assert [s.id for s in sessions.find_by_user(user.id)] == [newer.id, middle.id, older.id]


def test_find_by_user_breaks_ties_by_newest_id(sessions, db_session, user):
    # sessions started in one transaction have the same started_at
    ids = [add_session(db_session, user).id for _ in range(3)]

    assert [s.id for s in sessions.find_by_user(user.id)] == ids[::-1]


def test_find_by_user_filters_by_status(sessions, db_session, user):
    in_progress = add_session(db_session, user)
    completed = add_session(db_session, user, status="COMPLETED")

    assert [s.id for s in sessions.find_by_user(user.id, status="IN_PROGRESS")] == [in_progress.id]
    assert [s.id for s in sessions.find_by_user(user.id, status="COMPLETED")] == [completed.id]
    assert sessions.find_by_user(user.id, status="CANCELLED") == []


def test_find_by_user_loads_exercises_and_sets_in_a_fixed_number_of_queries(
    sessions, db_session, test_engine, user, bench_press, squat
):
    for _ in range(3):
        add_session(db_session, user, exercises=[(bench_press, [8, 8]), (squat, [5, 5, 5])])
    db_session.expunge_all()

    with count_queries(test_engine) as statements:
        loaded = [
            [(item.exercise_id, [s.reps for s in item.sets]) for item in workout_session.exercises]
            for workout_session in sessions.find_by_user(user.id)
        ]

    # the sessions, their exercises and their sets: three queries however many there are
    assert len(statements) == 3
    assert loaded == [[(bench_press, [8, 8]), (squat, [5, 5, 5])]] * 3


def test_update_and_delete_a_session(sessions, db_session, user, bench_press):
    workout_session = add_session(db_session, user, exercises=[(bench_press, [8])])
    session_id = workout_session.id
    session_exercise_id = workout_session.exercises[0].id
    workout_session.notes = "Felt strong"

    sessions.update(workout_session)
    assert not db_session.dirty  # flushed to the database
    db_session.expunge_all()
    assert sessions.get_by_id(session_id).notes == "Felt strong"

    sessions.delete(sessions.get_by_id(session_id))
    db_session.expunge_all()
    assert sessions.get_by_id(session_id) is None
    assert db_session.get(WorkoutSessionExercise, session_exercise_id) is None


# WorkoutSessionExerciseRepository


def test_session_exercise_lookups_stay_within_their_session(
    session_exercises, db_session, user, bench_press, squat
):
    workout_session = add_session(db_session, user, exercises=[(bench_press, []), (squat, [])])
    other_session = add_session(db_session, user, exercises=[(bench_press, [])])
    first, second = workout_session.exercises

    assert session_exercises.get_for_session(workout_session.id, first.id) is first
    assert session_exercises.get_for_session(other_session.id, first.id) is None
    assert session_exercises.get_by_order(workout_session.id, 2) is second
    assert session_exercises.get_by_order(workout_session.id, 3) is None


def test_create_update_and_delete_a_session_exercise(
    session_exercises, db_session, user, bench_press, squat
):
    workout_session = add_session(db_session, user)

    created = session_exercises.create(
        WorkoutSessionExercise(
            workout_session_id=workout_session.id, exercise_id=bench_press, exercise_order=1
        )
    )
    created.exercise_id = squat
    session_exercises.update(created)
    db_session.expunge_all()
    assert session_exercises.get_for_session(workout_session.id, created.id).exercise_id == squat

    session_exercises.delete(session_exercises.get_for_session(workout_session.id, created.id))
    db_session.expunge_all()
    assert session_exercises.get_for_session(workout_session.id, created.id) is None


# WorkoutSetRepository


def test_set_lookups_stay_within_their_session_exercise(sets, db_session, user, bench_press):
    first, second = add_session(
        db_session, user, exercises=[(bench_press, [8, 7]), (bench_press, [6])]
    ).exercises

    assert sets.get_for_session_exercise(first.id, first.sets[1].id) is first.sets[1]
    assert sets.get_for_session_exercise(second.id, first.sets[1].id) is None
    assert sets.get_by_set_number(first.id, 2) is first.sets[1]
    assert sets.get_by_set_number(second.id, 2) is None


def test_create_update_and_delete_a_set(sets, db_session, user, bench_press):
    session_exercise = add_session(db_session, user, exercises=[(bench_press, [])]).exercises[0]

    created = sets.create(
        WorkoutSet(
            workout_session_exercise_id=session_exercise.id,
            set_number=1,
            reps=8,
            weight_kg=50.0,
            rpe=7.5,
            completed=False,
            notes="Missed the last rep",
        )
    )
    created.reps = 7
    sets.update(created)
    db_session.expunge_all()
    stored = sets.get_for_session_exercise(session_exercise.id, created.id)
    assert (stored.reps, stored.weight_kg, stored.rpe, stored.completed) == (7, 50.0, 7.5, False)

    sets.delete(stored)
    db_session.expunge_all()
    assert sets.get_for_session_exercise(session_exercise.id, created.id) is None


def test_repositories_never_commit_or_roll_back(
    sessions, session_exercises, sets, db_session, user, bench_press
):
    with (
        patch.object(db_session, "commit", wraps=db_session.commit) as commit,
        patch.object(db_session, "rollback", wraps=db_session.rollback) as rollback,
    ):
        to_delete = sessions.create(WorkoutSession(user_id=user.id, status="IN_PROGRESS"))
        workout_session = sessions.create(WorkoutSession(user_id=user.id, status="IN_PROGRESS"))
        session_exercise = session_exercises.create(
            WorkoutSessionExercise(
                workout_session_id=workout_session.id, exercise_id=bench_press, exercise_order=1
            )
        )
        workout_set = sets.create(
            WorkoutSet(workout_session_exercise_id=session_exercise.id, set_number=1, reps=8)
        )
        exercise_to_delete = session_exercises.create(
            WorkoutSessionExercise(
                workout_session_id=workout_session.id, exercise_id=bench_press, exercise_order=2
            )
        )
        sessions.get_by_id(workout_session.id)
        sessions.get_for_user(user.id, workout_session.id)
        sessions.find_by_user(user.id, status="IN_PROGRESS")
        session_exercises.get_for_session(workout_session.id, session_exercise.id)
        session_exercises.get_by_order(workout_session.id, 1)
        sets.get_for_session_exercise(session_exercise.id, workout_set.id)
        sets.get_by_set_number(session_exercise.id, 1)
        workout_session.notes = "Updated"
        sessions.update(workout_session)
        session_exercise.notes = "Updated"
        session_exercises.update(session_exercise)
        workout_set.reps = 9
        sets.update(workout_set)
        sets.delete(workout_set)
        session_exercises.delete(exercise_to_delete)
        sessions.delete(to_delete)

    commit.assert_not_called()
    rollback.assert_not_called()
