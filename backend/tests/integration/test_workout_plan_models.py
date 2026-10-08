"""Integration tests for the workout plan models and database constraints.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

import pytest
from psycopg.errors import ForeignKeyViolation, RestrictViolation, UniqueViolation
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.models import Exercise, User, WorkoutPlan, WorkoutPlanExercise
from tests.integration.workout_plans import DATE, add_plan, add_user


@pytest.fixture
def user(db_session):
    return add_user(db_session, "plan-models@example.com")


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


def insert_plan_exercise(session, plan_id, exercise_id, exercise_order):
    session.execute(
        insert(WorkoutPlanExercise).values(
            workout_plan_id=plan_id,
            exercise_id=exercise_id,
            exercise_order=exercise_order,
            sets=3,
            reps=8,
        )
    )


def count_plan_exercises(session, plan_id):
    return session.scalar(
        select(func.count())
        .select_from(WorkoutPlanExercise)
        .where(WorkoutPlanExercise.workout_plan_id == plan_id)
    )


def test_plan_stores_its_prescribed_exercises_in_order(db_session, user, bench_press, squat):
    plan_id = add_plan(db_session, user, scheduled_date=DATE).id
    insert_plan_exercise(db_session, plan_id, squat, 2)
    insert_plan_exercise(db_session, plan_id, bench_press, 1)
    db_session.expunge_all()  # read from the database, not the session's identity map

    plan = db_session.get(WorkoutPlan, plan_id)

    assert (plan.user_id, plan.status, plan.scheduled_date) == (user.id, "DRAFT", DATE)
    assert [(item.exercise_order, item.exercise_id) for item in plan.exercises] == [
        (1, bench_press),
        (2, squat),
    ]
    assert all(item.workout_plan is plan for item in plan.exercises)


def test_optional_columns_are_null_and_timestamps_are_set(db_session, user, bench_press):
    plan = add_plan(db_session, user, exercise_ids=[bench_press])
    db_session.expunge_all()

    stored = db_session.get(WorkoutPlan, plan.id)
    exercise = stored.exercises[0]

    assert (stored.description, stored.scheduled_date) == (None, None)
    assert (exercise.weight_kg, exercise.rest_seconds, exercise.notes) == (None, None, None)
    for row in [stored, exercise]:
        assert row.created_at is not None and row.updated_at is not None


def test_exercise_order_is_unique_within_a_plan(db_session, user, bench_press, squat):
    plan = add_plan(db_session, user, exercise_ids=[bench_press])

    with pytest.raises(IntegrityError) as error:
        insert_plan_exercise(db_session, plan.id, squat, 1)

    assert isinstance(error.value.orig, UniqueViolation)


def test_plans_can_use_the_same_exercise_order(db_session, user, bench_press):
    first = add_plan(db_session, user, "First", exercise_ids=[bench_press])
    second = add_plan(db_session, user, "Second", exercise_ids=[bench_press])

    assert [item.exercise_order for item in first.exercises + second.exercises] == [1, 1]


def test_same_exercise_can_appear_twice_in_a_plan(db_session, user, squat):
    plan_id = add_plan(db_session, user, exercise_ids=[squat, squat]).id
    db_session.expunge_all()

    plan = db_session.get(WorkoutPlan, plan_id)

    assert [(item.exercise_order, item.exercise_id) for item in plan.exercises] == [
        (1, squat),
        (2, squat),
    ]


def test_users_can_have_several_plans_on_the_same_date(db_session, user):
    other = add_user(db_session, "plan-models-other@example.com")
    for owner, name in [(user, "Morning"), (user, "Evening"), (other, "Morning")]:
        add_plan(db_session, owner, name, scheduled_date=DATE)

    plans = db_session.scalars(select(WorkoutPlan).where(WorkoutPlan.scheduled_date == DATE))

    assert sorted((plan.user_id, plan.name) for plan in plans) == [
        (user.id, "Evening"),
        (user.id, "Morning"),
        (other.id, "Morning"),
    ]


def test_deleting_a_plan_deletes_its_exercises(db_session, user, bench_press, squat):
    plan_id = add_plan(db_session, user, exercise_ids=[bench_press, squat]).id

    db_session.execute(delete(WorkoutPlan).where(WorkoutPlan.id == plan_id))

    assert count_plan_exercises(db_session, plan_id) == 0
    assert db_session.get(Exercise, bench_press) is not None


def test_exercise_used_by_a_plan_cannot_be_deleted(db_session, user, bench_press):
    add_plan(db_session, user, exercise_ids=[bench_press])

    with pytest.raises(IntegrityError) as error:
        db_session.execute(delete(Exercise).where(Exercise.id == bench_press))

    assert isinstance(error.value.orig, RestrictViolation)


def test_user_with_plans_cannot_be_deleted(db_session, user):
    add_plan(db_session, user)

    with pytest.raises(IntegrityError) as error:
        db_session.execute(delete(User).where(User.id == user.id))

    assert isinstance(error.value.orig, RestrictViolation)


@pytest.mark.parametrize("missing", ["user", "plan", "exercise"])
def test_references_must_exist(db_session, user, bench_press, missing):
    plan = add_plan(db_session, user)

    with pytest.raises(IntegrityError) as error:
        if missing == "user":
            add_plan(db_session, User(id=-1))  # no user has this id
        else:
            insert_plan_exercise(
                db_session,
                -1 if missing == "plan" else plan.id,
                -1 if missing == "exercise" else bench_press,
                1,
            )

    assert isinstance(error.value.orig, ForeignKeyViolation)
