"""Integration tests for WorkoutPlanRepository and WorkoutPlanExerciseRepository.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

from contextlib import contextmanager
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import event

from app.models import WorkoutPlan, WorkoutPlanExercise
from app.repositories import WorkoutPlanExerciseRepository, WorkoutPlanRepository
from tests.integration.workout_plans import DATE, add_plan, add_user


@pytest.fixture
def plans(db_session):
    return WorkoutPlanRepository(db_session)


@pytest.fixture
def plan_exercises(db_session):
    return WorkoutPlanExerciseRepository(db_session)


@pytest.fixture
def user(db_session):
    return add_user(db_session, "plan-repository@example.com")


@pytest.fixture
def other_user(db_session):
    return add_user(db_session, "plan-repository-other@example.com")


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


def names(found):
    return [plan.name for plan in found]


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


# WorkoutPlanRepository


def test_create_flushes_the_plan_and_its_exercises(plans, db_session, user, bench_press):
    plan = plans.create(
        WorkoutPlan(
            user_id=user.id,
            name="Push Day",
            status="DRAFT",
            exercises=[
                WorkoutPlanExercise(exercise_id=bench_press, exercise_order=1, sets=3, reps=8)
            ],
        )
    )

    assert plan.id is not None
    assert plan.exercises[0].id is not None
    assert plan.exercises[0].workout_plan_id == plan.id
    assert not db_session.new  # flushed to the database


def test_get_by_id_returns_the_plan_with_its_exercises(plans, db_session, user, bench_press, squat):
    plan_id = add_plan(db_session, user, exercise_ids=[bench_press, squat]).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    plan = plans.get_by_id(plan_id)

    assert plan.name == "Push Day"
    assert [item.exercise_id for item in plan.exercises] == [bench_press, squat]


def test_get_by_id_returns_none_for_missing_plan(plans):
    assert plans.get_by_id(-1) is None


def test_get_for_user_returns_only_the_users_plan(plans, db_session, user, other_user):
    plan_id = add_plan(db_session, user).id
    db_session.expunge_all()

    assert plans.get_for_user(user.id, plan_id).id == plan_id
    assert plans.get_for_user(other_user.id, plan_id) is None
    assert plans.get_for_user(user.id, -1) is None


def test_find_by_user_returns_only_the_users_plans(plans, db_session, user, other_user):
    add_plan(db_session, user, "Mine")
    add_plan(db_session, other_user, "Theirs")

    assert names(plans.find_by_user(user.id)) == ["Mine"]
    assert names(plans.find_by_user(other_user.id)) == ["Theirs"]


def test_find_by_user_orders_by_date_then_newest_first(plans, db_session, user):
    created = [datetime(2026, 10, day, tzinfo=timezone.utc) for day in (1, 2, 3)]
    add_plan(db_session, user, "No date, older", created_at=created[0])
    add_plan(db_session, user, "Oct 10, older", scheduled_date=DATE, created_at=created[0])
    add_plan(db_session, user, "No date, newer", created_at=created[2])
    add_plan(db_session, user, "Oct 12", scheduled_date=date(2026, 10, 12), created_at=created[0])
    add_plan(db_session, user, "Oct 10, newer", scheduled_date=DATE, created_at=created[1])

    assert names(plans.find_by_user(user.id)) == [
        "Oct 12",
        "Oct 10, newer",
        "Oct 10, older",
        "No date, newer",
        "No date, older",
    ]


def test_find_by_user_breaks_ties_by_newest_id(plans, db_session, user):
    # plans created in one transaction have the same created_at
    for name in ["First", "Second", "Third"]:
        add_plan(db_session, user, name)

    assert names(plans.find_by_user(user.id)) == ["Third", "Second", "First"]


def test_find_by_user_filters_by_status_and_scheduled_date(plans, db_session, user, bench_press):
    add_plan(db_session, user, "Draft on date", scheduled_date=DATE)
    add_plan(db_session, user, "Draft, no date")
    add_plan(
        db_session,
        user,
        "Planned on date",
        status="PLANNED",
        scheduled_date=DATE,
        exercise_ids=[bench_press],
    )
    add_plan(db_session, user, "Cancelled", status="CANCELLED", scheduled_date=date(2026, 10, 11))

    assert names(plans.find_by_user(user.id, status="DRAFT")) == ["Draft on date", "Draft, no date"]
    assert names(plans.find_by_user(user.id, scheduled_date=DATE)) == [
        "Planned on date",
        "Draft on date",
    ]
    assert names(plans.find_by_user(user.id, status="PLANNED", scheduled_date=DATE)) == [
        "Planned on date"
    ]
    assert plans.find_by_user(user.id, status="CANCELLED", scheduled_date=DATE) == []


def test_find_by_user_loads_exercises_in_a_fixed_number_of_queries(
    plans, db_session, test_engine, user, bench_press, squat
):
    for number in range(3):
        add_plan(db_session, user, f"Plan {number}", exercise_ids=[bench_press, squat])
    db_session.expunge_all()

    with count_queries(test_engine) as statements:
        loaded = {
            plan.name: [item.exercise_id for item in plan.exercises]
            for plan in plans.find_by_user(user.id)
        }

    # the plans and their exercises: two queries however many plans there are
    assert len(statements) == 2
    assert loaded == {f"Plan {number}": [bench_press, squat] for number in range(3)}


def test_update_persists_changes(plans, db_session, user):
    plan = add_plan(db_session, user)
    plan.name = "Pull Day"
    plan.scheduled_date = DATE

    assert plans.update(plan) is plan
    assert not db_session.dirty  # flushed to the database
    db_session.expunge_all()
    stored = plans.get_by_id(plan.id)
    assert (stored.name, stored.scheduled_date) == ("Pull Day", DATE)


def test_delete_removes_the_plan_and_its_exercises(plans, plan_exercises, db_session, user, squat):
    plan = add_plan(db_session, user, exercise_ids=[squat])
    plan_id, plan_exercise_id = plan.id, plan.exercises[0].id

    plans.delete(plan)
    db_session.expunge_all()

    assert plans.get_by_id(plan_id) is None
    assert plan_exercises.get_for_plan(plan_id, plan_exercise_id) is None


# WorkoutPlanExerciseRepository


def test_create_adds_an_exercise_to_the_plan(plan_exercises, plans, db_session, user, squat):
    plan = add_plan(db_session, user)

    plan_exercise = plan_exercises.create(
        WorkoutPlanExercise(
            workout_plan_id=plan.id,
            exercise_id=squat,
            exercise_order=1,
            sets=5,
            reps=5,
            weight_kg=100.0,
            rest_seconds=180,
            notes="Belt on",
        )
    )

    assert plan_exercise.id is not None
    db_session.expunge_all()
    stored = plans.get_by_id(plan.id).exercises[0]
    assert (stored.sets, stored.reps, stored.weight_kg, stored.rest_seconds, stored.notes) == (
        5,
        5,
        100.0,
        180,
        "Belt on",
    )


def test_get_for_plan_returns_only_the_plans_exercise(plan_exercises, db_session, user, squat):
    plan = add_plan(db_session, user, exercise_ids=[squat])
    other_plan = add_plan(db_session, user, "Other", exercise_ids=[squat])
    plan_exercise_id = plan.exercises[0].id
    db_session.expunge_all()

    assert plan_exercises.get_for_plan(plan.id, plan_exercise_id).id == plan_exercise_id
    assert plan_exercises.get_for_plan(other_plan.id, plan_exercise_id) is None
    assert plan_exercises.get_for_plan(plan.id, -1) is None


def test_get_by_order_finds_the_exercise_at_a_position(plan_exercises, db_session, user, squat):
    plan = add_plan(db_session, user, exercise_ids=[squat, squat])

    assert plan_exercises.get_by_order(plan.id, 2).id == plan.exercises[1].id
    assert plan_exercises.get_by_order(plan.id, 3) is None


def test_update_and_delete_a_plan_exercise(plan_exercises, db_session, user, squat, bench_press):
    plan = add_plan(db_session, user, exercise_ids=[squat, squat])
    first, second = plan.exercises
    first.exercise_id, first.weight_kg = bench_press, 60.0

    plan_exercises.update(first)
    plan_exercises.delete(second)
    db_session.expunge_all()

    stored = plan_exercises.get_for_plan(plan.id, first.id)
    assert (stored.exercise_id, stored.weight_kg) == (bench_press, 60.0)
    assert plan_exercises.get_for_plan(plan.id, second.id) is None


def test_repositories_never_commit_or_roll_back(plans, plan_exercises, db_session, user, squat):
    with (
        patch.object(db_session, "commit", wraps=db_session.commit) as commit,
        patch.object(db_session, "rollback", wraps=db_session.rollback) as rollback,
    ):
        draft = plans.create(WorkoutPlan(user_id=user.id, name="To delete", status="DRAFT"))
        plan = plans.create(WorkoutPlan(user_id=user.id, name="Push Day", status="DRAFT"))
        plan_exercise = plan_exercises.create(
            WorkoutPlanExercise(
                workout_plan_id=plan.id, exercise_id=squat, exercise_order=1, sets=3, reps=8
            )
        )
        plans.get_by_id(plan.id)
        plans.get_for_user(user.id, plan.id)
        plans.find_by_user(user.id, status="DRAFT", scheduled_date=DATE)
        plan_exercises.get_for_plan(plan.id, plan_exercise.id)
        plan_exercises.get_by_order(plan.id, 1)
        plan.name = "Pull Day"
        plans.update(plan)
        plan_exercise.sets = 4
        plan_exercises.update(plan_exercise)
        plan_exercises.delete(plan_exercise)
        plans.delete(draft)

    commit.assert_not_called()
    rollback.assert_not_called()
