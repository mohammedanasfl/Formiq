"""Integration tests for WorkoutPlanExerciseService.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user and workout
plan tables before and after each test.
"""

from unittest.mock import patch

import pytest
from sqlalchemy.exc import DataError

from app.schemas import (
    UserCreate,
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutPlanExerciseUpdate,
    WorkoutPlanUpdate,
)
from app.services import UserService, WorkoutPlanExerciseService, WorkoutPlanService
from app.services.exceptions import (
    ExerciseNotFoundError,
    ExerciseOrderTakenError,
    InactiveExerciseError,
    InvalidWorkoutPlanError,
    WorkoutPlanExerciseNotFoundError,
    WorkoutPlanNotEditableError,
    WorkoutPlanNotFoundError,
)
from tests.integration.workout_plans import DATE, retire_exercise, stored_plan


@pytest.fixture
def service(service_session):
    return WorkoutPlanExerciseService(service_session)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="plan-exercises@example.com"))


@pytest.fixture
def bench_press(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Bench Press"]


@pytest.fixture
def squat(catalog_exercise_ids):
    return catalog_exercise_ids["Barbell Back Squat"]


def plan_exercise(exercise_id, exercise_order=1, **fields):
    return WorkoutPlanExerciseCreate(
        exercise_id=exercise_id, exercise_order=exercise_order, sets=3, reps=8, **fields
    )


@pytest.fixture
def make_plan(service_session, user, bench_press):
    """Creates a committed plan in the given status, with a date and the given
    exercises (by default one bench press at exercise_order 1)."""
    plans = WorkoutPlanService(service_session)

    def make(status="DRAFT", *, owner=None, exercises=None):
        owner_id = (owner or user).id
        plan = plans.create_plan(
            owner_id,
            WorkoutPlanCreate(
                name="Push Day",
                status="PLANNED" if status == "PLANNED" else "DRAFT",
                scheduled_date=DATE,
                exercises=[plan_exercise(bench_press)] if exercises is None else exercises,
            ),
        )
        if status == "CANCELLED":
            plan = plans.update_plan(owner_id, plan.id, WorkoutPlanUpdate(status="CANCELLED"))
        return plan

    return make


def stored_exercises(engine, plan_id):
    """(exercise_order, exercise_id) of the plan's committed exercises."""
    return [
        (item["exercise_order"], item["exercise_id"])
        for item in stored_plan(engine, plan_id)["exercises"]
    ]


# add_exercise


@pytest.mark.parametrize("status", ["DRAFT", "PLANNED"])
def test_add_exercise_commits_it(service, user, make_plan, squat, test_engine, status):
    plan = make_plan(status)

    added = service.add_exercise(
        user.id, plan.id, plan_exercise(squat, 2, weight_kg=100.0, rest_seconds=180, notes="Deep")
    )

    assert added.id is not None
    assert added.workout_plan_id == plan.id
    stored = stored_plan(test_engine, plan.id)["exercises"][1]  # committed
    assert {key: stored[key] for key in ["exercise_id", "exercise_order", "sets", "reps"]} == {
        "exercise_id": squat,
        "exercise_order": 2,
        "sets": 3,
        "reps": 8,
    }
    assert (stored["weight_kg"], stored["rest_seconds"], stored["notes"]) == (100.0, 180, "Deep")


def test_add_exercise_rejects_an_unknown_exercise(
    service, user, make_plan, bench_press, test_engine
):
    plan = make_plan()

    with pytest.raises(ExerciseNotFoundError, match="exercise 2147483647 does not exist"):
        service.add_exercise(user.id, plan.id, plan_exercise(2_147_483_647, 2))

    assert stored_exercises(test_engine, plan.id) == [(1, bench_press)]


def test_add_exercise_rejects_a_taken_exercise_order(
    service, user, make_plan, bench_press, squat, test_engine
):
    plan = make_plan()

    with pytest.raises(ExerciseOrderTakenError, match="exercise_order 1"):
        service.add_exercise(user.id, plan.id, plan_exercise(squat, 1))

    assert stored_exercises(test_engine, plan.id) == [(1, bench_press)]


def test_add_the_same_exercise_again_at_another_position(
    service, user, make_plan, bench_press, test_engine
):
    plan = make_plan()

    service.add_exercise(user.id, plan.id, plan_exercise(bench_press, 2))

    assert stored_exercises(test_engine, plan.id) == [(1, bench_press), (2, bench_press)]


def test_cancelled_plan_accepts_no_exercises(service, user, make_plan, squat, test_engine):
    plan = make_plan("CANCELLED")
    before = stored_plan(test_engine, plan.id)

    with pytest.raises(WorkoutPlanNotEditableError):
        service.add_exercise(user.id, plan.id, plan_exercise(squat, 2))

    assert stored_plan(test_engine, plan.id) == before


# update_exercise


def test_update_exercise_changes_only_the_supplied_fields(
    service, user, make_plan, squat, test_engine
):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)["exercises"][0]

    updated = service.update_exercise(
        user.id, plan.id, before["id"], WorkoutPlanExerciseUpdate(exercise_id=squat, reps=5)
    )

    after = stored_plan(test_engine, plan.id)["exercises"][0]
    assert (updated.exercise_id, after["exercise_id"], after["reps"]) == (squat, squat, 5)
    unchanged = set(before) - {"exercise_id", "reps", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


def test_update_exercise_can_clear_optional_fields(
    service, user, make_plan, bench_press, test_engine
):
    plan = make_plan(
        exercises=[plan_exercise(bench_press, weight_kg=50.0, rest_seconds=90, notes="x")]
    )
    plan_exercise_id = plan.exercises[0].id
    nullable = {"weight_kg": None, "rest_seconds": None, "notes": None}

    service.update_exercise(
        user.id, plan.id, plan_exercise_id, WorkoutPlanExerciseUpdate(**nullable)
    )

    stored = stored_plan(test_engine, plan.id)["exercises"][0]
    assert {key: stored[key] for key in nullable} == nullable


@pytest.mark.parametrize("field", ["exercise_id", "exercise_order", "sets", "reps"])
def test_update_exercise_rejects_null_for_required_fields(
    service, user, make_plan, test_engine, field
):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)

    with pytest.raises(InvalidWorkoutPlanError, match=f"cannot be null: {field}"):
        service.update_exercise(
            user.id, plan.id, plan.exercises[0].id, WorkoutPlanExerciseUpdate(**{field: None})
        )

    assert stored_plan(test_engine, plan.id) == before


def test_update_exercise_rejects_an_unknown_exercise(
    service, user, make_plan, bench_press, test_engine
):
    plan = make_plan()

    with pytest.raises(ExerciseNotFoundError):
        service.update_exercise(
            user.id,
            plan.id,
            plan.exercises[0].id,
            WorkoutPlanExerciseUpdate(exercise_id=2_147_483_647),
        )

    assert stored_exercises(test_engine, plan.id) == [(1, bench_press)]


def test_update_exercise_rejects_a_taken_exercise_order(
    service, user, make_plan, bench_press, squat, test_engine
):
    plan = make_plan(exercises=[plan_exercise(bench_press, 1), plan_exercise(squat, 2)])
    first = plan.exercises[0].id

    with pytest.raises(ExerciseOrderTakenError):
        service.update_exercise(
            user.id, plan.id, first, WorkoutPlanExerciseUpdate(exercise_order=2)
        )
    # an exercise keeping its own position is no conflict
    service.update_exercise(
        user.id, plan.id, first, WorkoutPlanExerciseUpdate(exercise_order=1, sets=5)
    )
    service.update_exercise(user.id, plan.id, first, WorkoutPlanExerciseUpdate(exercise_order=3))

    assert stored_exercises(test_engine, plan.id) == [(2, squat), (3, bench_press)]


# remove_exercise


def test_remove_exercise_deletes_only_it(service, user, make_plan, bench_press, squat, test_engine):
    plan = make_plan(exercises=[plan_exercise(bench_press, 1), plan_exercise(squat, 2)])

    service.remove_exercise(user.id, plan.id, plan.exercises[0].id)

    assert stored_exercises(test_engine, plan.id) == [(2, squat)]


def test_planned_plan_keeps_at_least_one_exercise(
    service, user, make_plan, bench_press, squat, test_engine
):
    plan = make_plan("PLANNED", exercises=[plan_exercise(bench_press, 1), plan_exercise(squat, 2)])
    first, second = (item.id for item in plan.exercises)

    service.remove_exercise(user.id, plan.id, first)
    with pytest.raises(InvalidWorkoutPlanError, match="needs at least one exercise"):
        service.remove_exercise(user.id, plan.id, second)

    assert stored_exercises(test_engine, plan.id) == [(2, squat)]


def test_draft_plan_can_lose_its_last_exercise(service, user, make_plan, test_engine):
    plan = make_plan()

    service.remove_exercise(user.id, plan.id, plan.exercises[0].id)

    assert stored_exercises(test_engine, plan.id) == []


# rules shared by the three operations


@pytest.mark.parametrize("operation", ["update", "remove"])
def test_cancelled_plan_exercises_cannot_be_changed(
    service, user, make_plan, test_engine, operation
):
    plan = make_plan("CANCELLED")
    before = stored_plan(test_engine, plan.id)
    plan_exercise_id = before["exercises"][0]["id"]

    with pytest.raises(WorkoutPlanNotEditableError):
        if operation == "update":
            service.update_exercise(
                user.id, plan.id, plan_exercise_id, WorkoutPlanExerciseUpdate(sets=5)
            )
        else:
            service.remove_exercise(user.id, plan.id, plan_exercise_id)

    assert stored_plan(test_engine, plan.id) == before


@pytest.mark.parametrize("operation", ["add", "update", "remove"])
def test_another_users_plan_exercises_are_not_found(
    service, service_session, user, make_plan, squat, test_engine, operation
):
    other = UserService(service_session).create_user(UserCreate(email="other@example.com"))
    plan = make_plan(owner=other)
    before = stored_plan(test_engine, plan.id)
    plan_exercise_id = before["exercises"][0]["id"]

    with pytest.raises(WorkoutPlanNotFoundError, match=f"user {user.id} has no workout plan"):
        if operation == "add":
            service.add_exercise(user.id, plan.id, plan_exercise(squat, 2))
        elif operation == "update":
            service.update_exercise(
                user.id, plan.id, plan_exercise_id, WorkoutPlanExerciseUpdate(sets=5)
            )
        else:
            service.remove_exercise(user.id, plan.id, plan_exercise_id)

    assert stored_plan(test_engine, plan.id) == before


@pytest.mark.parametrize("operation", ["update", "remove"])
def test_exercise_of_another_plan_is_not_found(service, user, make_plan, test_engine, operation):
    plan = make_plan()
    other_plan = make_plan()
    other_exercise_id = other_plan.exercises[0].id
    before = stored_plan(test_engine, other_plan.id)

    with pytest.raises(WorkoutPlanExerciseNotFoundError):
        if operation == "update":
            service.update_exercise(
                user.id, plan.id, other_exercise_id, WorkoutPlanExerciseUpdate(sets=5)
            )
        else:
            service.remove_exercise(user.id, plan.id, other_exercise_id)

    assert stored_plan(test_engine, other_plan.id) == before


def test_failed_add_rolls_back(
    service, service_session, user, make_plan, bench_press, squat, test_engine
):
    plan = make_plan()
    # beyond the sets column: model_construct skips the schema check, so the
    # insert itself fails in the database
    too_many = WorkoutPlanExerciseCreate.model_construct(
        exercise_id=squat, exercise_order=2, sets=2_147_483_648, reps=8
    )

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.add_exercise(user.id, plan.id, too_many)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert stored_exercises(test_engine, plan.id) == [(1, bench_press)]
    # the session is usable again after the rollback
    service.add_exercise(user.id, plan.id, plan_exercise(squat, 2))
    assert stored_exercises(test_engine, plan.id) == [(1, bench_press), (2, squat)]


# inactive (retired) exercises


def test_active_exercise_can_be_added(service, user, make_plan, retirable_exercise_id, test_engine):
    plan = make_plan()

    service.add_exercise(user.id, plan.id, plan_exercise(retirable_exercise_id, 2))

    assert stored_exercises(test_engine, plan.id)[1] == (2, retirable_exercise_id)


def test_inactive_exercise_cannot_be_added(
    service, user, make_plan, retirable_exercise_id, test_engine
):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)
    retire_exercise(test_engine, retirable_exercise_id)

    inactive = f"exercise {retirable_exercise_id} is inactive"
    with pytest.raises(InactiveExerciseError, match=inactive):
        service.add_exercise(user.id, plan.id, plan_exercise(retirable_exercise_id, 2))

    assert stored_plan(test_engine, plan.id) == before


def test_plan_exercise_cannot_switch_to_an_inactive_exercise(
    service, user, make_plan, retirable_exercise_id, test_engine
):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)
    retire_exercise(test_engine, retirable_exercise_id)

    with pytest.raises(InactiveExerciseError):
        service.update_exercise(
            user.id,
            plan.id,
            plan.exercises[0].id,
            WorkoutPlanExerciseUpdate(exercise_id=retirable_exercise_id),
        )

    assert stored_plan(test_engine, plan.id) == before


def test_plan_exercise_is_kept_when_its_exercise_is_retired(
    service, user, make_plan, bench_press, retirable_exercise_id, test_engine
):
    plan = make_plan(
        exercises=[plan_exercise(bench_press, 1), plan_exercise(retirable_exercise_id, 2)]
    )
    retired_id = plan.exercises[1].id

    retire_exercise(test_engine, retirable_exercise_id)

    # not deleted or changed
    assert stored_exercises(test_engine, plan.id) == [(1, bench_press), (2, retirable_exercise_id)]
    # and still editable, as long as it keeps its exercise
    service.update_exercise(
        user.id,
        plan.id,
        retired_id,
        WorkoutPlanExerciseUpdate(exercise_id=retirable_exercise_id, sets=5),
    )
    assert stored_plan(test_engine, plan.id)["exercises"][1]["sets"] == 5
