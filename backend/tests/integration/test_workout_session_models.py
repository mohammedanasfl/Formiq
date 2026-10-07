"""Integration tests for the workout session models and database constraints.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

import pytest
from psycopg.errors import ForeignKeyViolation, RestrictViolation, UniqueViolation
from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from app.models import (
    Exercise,
    User,
    WorkoutPlan,
    WorkoutPlanExercise,
    WorkoutSession,
    WorkoutSessionExercise,
    WorkoutSet,
)
from tests.integration.workout_plans import add_plan, add_user
from tests.integration.workout_sessions import add_session


@pytest.fixture
def user(db_session):
    return add_user(db_session, "session-models@example.com")


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


def count(session, model, **where):
    query = select(func.count()).select_from(model)
    for column, value in where.items():
        query = query.where(getattr(model, column) == value)
    return session.scalar(query)


def test_session_stores_its_exercises_and_sets_in_order(db_session, user, bench_press, squat):
    session_id = add_session(
        db_session, user, exercises=[(bench_press, [8, 8, 7]), (squat, [5])]
    ).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    stored = db_session.get(WorkoutSession, session_id)

    assert [(item.exercise_order, item.exercise_id) for item in stored.exercises] == [
        (1, bench_press),
        (2, squat),
    ]
    assert [(s.set_number, s.reps) for s in stored.exercises[0].sets] == [(1, 8), (2, 8), (3, 7)]
    assert stored.exercises[0].workout_session is stored
    assert stored.exercises[0].sets[0].workout_session_exercise is stored.exercises[0]


def test_defaults(db_session, user, bench_press):
    session_id = add_session(db_session, user, exercises=[(bench_press, [8])]).id
    db_session.expunge_all()

    stored = db_session.get(WorkoutSession, session_id)
    workout_set = stored.exercises[0].sets[0]

    # started_at comes from the database; completed_at only when completed
    assert stored.started_at is not None
    assert (stored.completed_at, stored.workout_plan_id, stored.notes) == (None, None, None)
    assert stored.exercises[0].plan_exercise_id is None
    # a recorded set is completed unless it says otherwise
    assert workout_set.completed is True
    assert (workout_set.weight_kg, workout_set.rpe, workout_set.notes) == (None, None, None)
    for row in [stored, stored.exercises[0], workout_set]:
        assert row.created_at is not None and row.updated_at is not None


def test_exercise_order_is_unique_within_a_session(db_session, user, bench_press, squat):
    workout_session = add_session(db_session, user, exercises=[(bench_press, [])])

    with pytest.raises(IntegrityError) as error:
        db_session.execute(
            insert(WorkoutSessionExercise).values(
                workout_session_id=workout_session.id, exercise_id=squat, exercise_order=1
            )
        )

    assert isinstance(error.value.orig, UniqueViolation)


def test_set_number_is_unique_within_a_session_exercise(db_session, user, bench_press):
    session_exercise = add_session(db_session, user, exercises=[(bench_press, [8])]).exercises[0]

    with pytest.raises(IntegrityError) as error:
        db_session.execute(
            insert(WorkoutSet).values(
                workout_session_exercise_id=session_exercise.id, set_number=1, reps=6
            )
        )

    assert isinstance(error.value.orig, UniqueViolation)


def test_positions_repeat_across_parents_and_exercises_repeat_in_a_session(db_session, user, squat):
    first = add_session(db_session, user, exercises=[(squat, [5, 5]), (squat, [5])])
    second = add_session(db_session, user, exercises=[(squat, [5])])

    # the same exercise twice in one session, and order 1 and set 1 in each parent
    assert [item.exercise_id for item in first.exercises] == [squat, squat]
    assert [item.exercise_order for item in first.exercises + second.exercises] == [1, 2, 1]
    assert [s.set_number for item in first.exercises for s in item.sets] == [1, 2, 1]


def test_a_user_can_have_several_sessions_a_day(db_session, user):
    for _ in range(3):
        add_session(db_session, user)

    assert count(db_session, WorkoutSession, user_id=user.id) == 3


def test_deleting_a_session_deletes_its_exercises_and_sets(db_session, user, bench_press):
    workout_session = add_session(db_session, user, exercises=[(bench_press, [8, 8])])
    session_exercise_id = workout_session.exercises[0].id

    db_session.execute(delete(WorkoutSession).where(WorkoutSession.id == workout_session.id))

    assert count(db_session, WorkoutSessionExercise, workout_session_id=workout_session.id) == 0
    assert count(db_session, WorkoutSet, workout_session_exercise_id=session_exercise_id) == 0


def test_deleting_a_session_exercise_deletes_its_sets(db_session, user, bench_press):
    session_exercise_id = (
        add_session(db_session, user, exercises=[(bench_press, [8])]).exercises[0].id
    )

    db_session.execute(
        delete(WorkoutSessionExercise).where(WorkoutSessionExercise.id == session_exercise_id)
    )

    assert count(db_session, WorkoutSet, workout_session_exercise_id=session_exercise_id) == 0


def test_deleting_its_plan_keeps_the_session_and_unlinks_it(db_session, user, bench_press):
    plan = add_plan(db_session, user, exercise_ids=[bench_press])
    workout_session = add_session(db_session, user, workout_plan_id=plan.id)
    session_exercise = WorkoutSessionExercise(
        workout_session_id=workout_session.id,
        exercise_id=bench_press,
        exercise_order=1,
        plan_exercise_id=plan.exercises[0].id,
    )
    db_session.add(session_exercise)
    db_session.flush()

    db_session.execute(delete(WorkoutPlan).where(WorkoutPlan.id == plan.id))
    db_session.expire_all()

    # SET NULL: the history stays, without the links to the deleted plan
    assert workout_session.workout_plan_id is None
    assert session_exercise.plan_exercise_id is None
    assert session_exercise.exercise_id == bench_press


def test_deleting_a_plan_exercise_unlinks_the_session_exercise(db_session, user, bench_press):
    plan = add_plan(db_session, user, exercise_ids=[bench_press])
    workout_session = add_session(db_session, user, workout_plan_id=plan.id)
    db_session.add(
        WorkoutSessionExercise(
            workout_session_id=workout_session.id,
            exercise_id=bench_press,
            exercise_order=1,
            plan_exercise_id=plan.exercises[0].id,
        )
    )
    db_session.flush()

    db_session.execute(
        delete(WorkoutPlanExercise).where(WorkoutPlanExercise.id == plan.exercises[0].id)
    )
    db_session.expire_all()

    assert [(item.exercise_id, item.plan_exercise_id) for item in workout_session.exercises] == [
        (bench_press, None)
    ]
    assert workout_session.workout_plan_id == plan.id


@pytest.mark.parametrize("model", [User, Exercise])
def test_user_or_exercise_in_the_history_cannot_be_deleted(db_session, user, bench_press, model):
    add_session(db_session, user, exercises=[(bench_press, [8])])
    row_id = user.id if model is User else bench_press

    with pytest.raises(IntegrityError) as error:
        db_session.execute(delete(model).where(model.id == row_id))

    assert isinstance(error.value.orig, RestrictViolation)


def test_retiring_an_exercise_keeps_the_history(db_session, user, bench_press):
    workout_session = add_session(db_session, user, exercises=[(bench_press, [8])])

    db_session.execute(update(Exercise).where(Exercise.id == bench_press).values(is_active=False))
    db_session.expire_all()

    assert [item.exercise_id for item in workout_session.exercises] == [bench_press]


@pytest.mark.parametrize(
    "missing", ["user", "plan", "session", "plan exercise", "exercise", "session exercise"]
)
def test_references_must_exist(db_session, user, bench_press, missing):
    workout_session = add_session(db_session, user, exercises=[(bench_press, [])])

    with pytest.raises(IntegrityError) as error:
        if missing in ("user", "plan"):
            db_session.execute(
                insert(WorkoutSession).values(
                    user_id=-1 if missing == "user" else user.id,
                    workout_plan_id=-1 if missing == "plan" else None,
                    status="IN_PROGRESS",
                )
            )
        elif missing == "session exercise":
            db_session.execute(
                insert(WorkoutSet).values(workout_session_exercise_id=-1, set_number=1, reps=8)
            )
        else:
            db_session.execute(
                insert(WorkoutSessionExercise).values(
                    workout_session_id=-1 if missing == "session" else workout_session.id,
                    plan_exercise_id=-1 if missing == "plan exercise" else None,
                    exercise_id=-1 if missing == "exercise" else bench_press,
                    exercise_order=2,
                )
            )

    assert isinstance(error.value.orig, ForeignKeyViolation)
