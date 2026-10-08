"""Integration tests for WorkoutPlanService.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user and workout
plan tables before and after each test.
"""

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy.exc import DataError

from app.models import WorkoutPlan, WorkoutPlanExercise
from app.schemas import (
    UserCreate,
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutPlanFilters,
    WorkoutPlanUpdate,
)
from app.services import UserService, WorkoutPlanService
from app.services.exceptions import (
    ExerciseNotFoundError,
    InactiveExerciseError,
    InvalidStatusTransitionError,
    InvalidWorkoutPlanError,
    UserNotFoundError,
    WorkoutPlanNotDeletableError,
    WorkoutPlanNotEditableError,
    WorkoutPlanNotFoundError,
)
from tests.integration.workout_plans import DATE, count_rows, retire_exercise, stored_plan


@pytest.fixture
def service(service_session):
    return WorkoutPlanService(service_session)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="plan-service@example.com"))


@pytest.fixture
def other_user(service_session):
    return UserService(service_session).create_user(UserCreate(email="plan-other@example.com"))


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
def make_plan(service, user, bench_press):
    """Creates a committed plan in the given status, with a date and one exercise."""

    def make(status="DRAFT", *, owner=None, scheduled_date=DATE, with_exercise=True):
        owner_id = (owner or user).id
        plan = service.create_plan(
            owner_id,
            WorkoutPlanCreate(
                name="Push Day",
                status="PLANNED" if status == "PLANNED" else "DRAFT",
                scheduled_date=scheduled_date,
                exercises=[plan_exercise(bench_press)] if with_exercise else [],
            ),
        )
        if status == "CANCELLED":
            plan = service.update_plan(owner_id, plan.id, WorkoutPlanUpdate(status="CANCELLED"))
        return plan

    return make


# create_plan


def test_create_draft_plan_with_only_a_name(service, user, test_engine):
    plan = service.create_plan(user.id, WorkoutPlanCreate(name="Push Day"))

    stored = stored_plan(test_engine, plan.id)  # committed, so visible to other sessions
    assert stored["user_id"] == user.id
    assert (stored["name"], stored["status"], stored["scheduled_date"]) == (
        "Push Day",
        "DRAFT",
        None,
    )
    assert stored["exercises"] == []


def test_create_plan_requires_an_existing_user(service, test_engine):
    with pytest.raises(UserNotFoundError):
        service.create_plan(-1, WorkoutPlanCreate(name="Push Day"))

    assert count_rows(test_engine, WorkoutPlan) == 0


def test_create_planned_plan_with_its_exercises(service, user, bench_press, squat, test_engine):
    plan = service.create_plan(
        user.id,
        WorkoutPlanCreate(
            name="Push Day",
            status="PLANNED",
            scheduled_date=DATE,
            exercises=[
                plan_exercise(squat, 2),
                plan_exercise(bench_press, 1, weight_kg=50.0, rest_seconds=120, notes="Slow"),
            ],
        ),
    )

    stored = stored_plan(test_engine, plan.id)
    assert (stored["status"], stored["scheduled_date"]) == ("PLANNED", DATE)
    assert [
        (item["exercise_order"], item["exercise_id"], item["weight_kg"], item["notes"])
        for item in stored["exercises"]
    ] == [(1, bench_press, 50.0, "Slow"), (2, squat, None, None)]
    assert [item.exercise_order for item in plan.exercises] == [1, 2]


@pytest.mark.parametrize(
    ("scheduled_date", "with_exercise", "message"),
    [(None, True, "needs a scheduled_date"), (DATE, False, "needs at least one exercise")],
)
def test_create_planned_plan_needs_a_date_and_an_exercise(
    service, user, bench_press, test_engine, scheduled_date, with_exercise, message
):
    plan_data = WorkoutPlanCreate(
        name="Push Day",
        status="PLANNED",
        scheduled_date=scheduled_date,
        exercises=[plan_exercise(bench_press)] if with_exercise else [],
    )

    with pytest.raises(InvalidWorkoutPlanError, match=message):
        service.create_plan(user.id, plan_data)

    assert count_rows(test_engine, WorkoutPlan) == 0


def test_create_plan_with_an_unknown_exercise_saves_nothing(
    service, user, bench_press, test_engine
):
    plan_data = WorkoutPlanCreate(
        name="Push Day", exercises=[plan_exercise(bench_press, 1), plan_exercise(2_147_483_647, 2)]
    )

    with pytest.raises(ExerciseNotFoundError, match="exercise 2147483647 does not exist"):
        service.create_plan(user.id, plan_data)

    assert count_rows(test_engine, WorkoutPlan) == 0
    assert count_rows(test_engine, WorkoutPlanExercise) == 0


def test_create_plan_rejects_a_repeated_exercise_order(service, user, bench_press, squat):
    plan_data = WorkoutPlanCreate(
        name="Push Day", exercises=[plan_exercise(bench_press, 1), plan_exercise(squat, 1)]
    )

    with pytest.raises(InvalidWorkoutPlanError, match="exercise_order"):
        service.create_plan(user.id, plan_data)


def test_create_plan_can_repeat_an_exercise(service, user, squat):
    plan = service.create_plan(
        user.id,
        WorkoutPlanCreate(
            name="Squats", exercises=[plan_exercise(squat, 1), plan_exercise(squat, 2)]
        ),
    )

    assert [item.exercise_id for item in plan.exercises] == [squat, squat]


# list_plans and get_plan


def test_list_plans_returns_only_the_users_plans(service, user, other_user, make_plan):
    mine = make_plan()
    make_plan(owner=other_user)

    assert [plan.id for plan in service.list_plans(user.id, WorkoutPlanFilters())] == [mine.id]


def test_list_plans_applies_the_filters(service, user, make_plan):
    planned = make_plan("PLANNED")
    make_plan("DRAFT")
    make_plan("PLANNED", scheduled_date=date(2026, 10, 11))

    found = service.list_plans(user.id, WorkoutPlanFilters(status="PLANNED", scheduled_date=DATE))

    assert [plan.id for plan in found] == [planned.id]


def test_list_plans_of_a_missing_user_is_an_error(service):
    with pytest.raises(UserNotFoundError):
        service.list_plans(-1, WorkoutPlanFilters())


def test_get_plan_returns_only_the_users_plan(service, user, other_user, make_plan):
    plan = make_plan()

    assert service.get_plan(user.id, plan.id).id == plan.id
    assert service.get_plan(other_user.id, plan.id) is None
    assert service.get_plan(user.id, -1) is None


# update_plan


def test_update_plan_changes_only_the_supplied_fields(service, user, make_plan, test_engine):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)

    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(name="Pull Day", description="Back"))

    after = stored_plan(test_engine, plan.id)
    assert (after["name"], after["description"]) == ("Pull Day", "Back")
    unchanged = set(before) - {"name", "description", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


def test_update_plan_can_clear_optional_fields(service, user, make_plan, test_engine):
    plan = make_plan()
    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(description="Back"))

    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(description=None, scheduled_date=None))

    stored = stored_plan(test_engine, plan.id)
    assert (stored["description"], stored["scheduled_date"]) == (None, None)


@pytest.mark.parametrize("field", ["name", "status"])
def test_update_plan_rejects_null_for_required_fields(service, user, make_plan, test_engine, field):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)

    with pytest.raises(InvalidWorkoutPlanError, match=f"cannot be null: {field}"):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(**{field: None}))

    assert stored_plan(test_engine, plan.id) == before


@pytest.mark.parametrize(
    ("current", "new"),
    [
        ("DRAFT", "DRAFT"),
        ("DRAFT", "PLANNED"),
        ("DRAFT", "CANCELLED"),
        ("PLANNED", "PLANNED"),
        ("PLANNED", "CANCELLED"),
        ("CANCELLED", "CANCELLED"),
    ],
)
def test_allowed_status_changes(service, user, make_plan, test_engine, current, new):
    plan = make_plan(current)

    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(status=new))

    assert stored_plan(test_engine, plan.id)["status"] == new


@pytest.mark.parametrize(
    ("current", "new"),
    [("CANCELLED", "PLANNED"), ("CANCELLED", "DRAFT"), ("PLANNED", "DRAFT")],
)
def test_disallowed_status_changes(service, user, make_plan, test_engine, current, new):
    plan = make_plan(current)

    with pytest.raises(InvalidStatusTransitionError):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(status=new))

    assert stored_plan(test_engine, plan.id)["status"] == current


def test_planning_a_draft_needs_a_scheduled_date(service, user, make_plan, test_engine):
    plan = make_plan(scheduled_date=None)

    with pytest.raises(InvalidWorkoutPlanError, match="needs a scheduled_date"):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(status="PLANNED"))
    assert stored_plan(test_engine, plan.id)["status"] == "DRAFT"

    # the date can be set in the same update
    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(status="PLANNED", scheduled_date=DATE))
    assert stored_plan(test_engine, plan.id)["status"] == "PLANNED"


def test_planning_a_draft_needs_an_exercise(service, user, make_plan, test_engine):
    plan = make_plan(with_exercise=False)

    with pytest.raises(InvalidWorkoutPlanError, match="needs at least one exercise"):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(status="PLANNED"))

    assert stored_plan(test_engine, plan.id)["status"] == "DRAFT"


def test_planned_plan_keeps_its_scheduled_date(service, user, make_plan, test_engine):
    plan = make_plan("PLANNED")

    with pytest.raises(InvalidWorkoutPlanError, match="needs a scheduled_date"):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(scheduled_date=None))

    assert stored_plan(test_engine, plan.id)["scheduled_date"] == DATE


def test_planned_plan_can_be_edited(service, user, make_plan, test_engine):
    plan = make_plan("PLANNED")
    changes = {"name": "Pull Day", "description": "Back", "scheduled_date": date(2026, 10, 12)}

    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(**changes))

    stored = stored_plan(test_engine, plan.id)
    assert {key: stored[key] for key in changes} == changes
    assert stored["status"] == "PLANNED"


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "Pull Day"},
        {"description": None},
        {"scheduled_date": date(2026, 10, 12)},
        {"status": "CANCELLED", "name": "Pull Day"},
    ],
)
def test_cancelled_plan_cannot_be_edited(service, user, make_plan, test_engine, changes):
    plan = make_plan("CANCELLED")
    before = stored_plan(test_engine, plan.id)

    with pytest.raises(WorkoutPlanNotEditableError):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(**changes))

    assert stored_plan(test_engine, plan.id) == before


# delete_plan


def test_delete_draft_plan_deletes_it_and_its_exercises(service, user, make_plan, test_engine):
    plan = make_plan()

    service.delete_plan(user.id, plan.id)

    assert stored_plan(test_engine, plan.id) is None
    assert count_rows(test_engine, WorkoutPlanExercise) == 0


@pytest.mark.parametrize("status", ["PLANNED", "CANCELLED"])
def test_only_draft_plans_can_be_deleted(service, user, make_plan, test_engine, status):
    plan = make_plan(status)

    with pytest.raises(WorkoutPlanNotDeletableError, match="only DRAFT"):
        service.delete_plan(user.id, plan.id)

    assert stored_plan(test_engine, plan.id)["status"] == status


# ownership and transactions


def test_another_users_plan_cannot_be_changed_or_deleted(
    service, user, other_user, make_plan, test_engine
):
    plan = make_plan(owner=other_user)
    before = stored_plan(test_engine, plan.id)

    with pytest.raises(WorkoutPlanNotFoundError, match=f"user {user.id} has no workout plan"):
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(name="Mine now"))
    with pytest.raises(WorkoutPlanNotFoundError):
        service.delete_plan(user.id, plan.id)

    assert stored_plan(test_engine, plan.id) == before


def test_missing_plan_cannot_be_changed_or_deleted(service, user):
    with pytest.raises(WorkoutPlanNotFoundError):
        service.update_plan(user.id, 2_147_483_647, WorkoutPlanUpdate(name="Pull Day"))
    with pytest.raises(WorkoutPlanNotFoundError):
        service.delete_plan(user.id, 2_147_483_647)


def test_failed_create_rolls_back(service, service_session, user, test_engine):
    # longer than the name column: model_construct skips the schema check, so
    # the insert itself fails in the database
    too_long = WorkoutPlanCreate.model_construct(name="x" * 151)

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.create_plan(user.id, too_long)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert count_rows(test_engine, WorkoutPlan) == 0
    # the session is usable again after the rollback
    assert service.create_plan(user.id, WorkoutPlanCreate(name="Push Day")).id is not None


def test_failed_update_rolls_back(service, service_session, user, make_plan, test_engine):
    plan = make_plan()
    before = stored_plan(test_engine, plan.id)
    too_long = WorkoutPlanUpdate.model_construct(description="Back", name="x" * 151)

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.update_plan(user.id, plan.id, too_long)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert stored_plan(test_engine, plan.id) == before
    assert (
        service.update_plan(user.id, plan.id, WorkoutPlanUpdate(name="Pull Day")).name == "Pull Day"
    )


# inactive (retired) exercises


def test_create_plan_with_an_inactive_exercise_fails(
    service, user, retirable_exercise_id, test_engine
):
    retire_exercise(test_engine, retirable_exercise_id)
    plan_data = WorkoutPlanCreate(name="Push Day", exercises=[plan_exercise(retirable_exercise_id)])

    inactive = f"exercise {retirable_exercise_id} is inactive"
    with pytest.raises(InactiveExerciseError, match=inactive):
        service.create_plan(user.id, plan_data)

    assert count_rows(test_engine, WorkoutPlan) == 0


def test_create_plan_saves_nothing_when_one_exercise_is_inactive(
    service, user, bench_press, squat, retirable_exercise_id, test_engine
):
    retire_exercise(test_engine, retirable_exercise_id)
    plan_data = WorkoutPlanCreate(
        name="Push Day",
        status="PLANNED",
        scheduled_date=DATE,
        exercises=[
            plan_exercise(bench_press, 1),
            plan_exercise(squat, 2),
            plan_exercise(retirable_exercise_id, 3),
        ],
    )

    with pytest.raises(InactiveExerciseError):
        service.create_plan(user.id, plan_data)

    assert count_rows(test_engine, WorkoutPlan) == 0
    assert count_rows(test_engine, WorkoutPlanExercise) == 0


def test_plan_with_an_exercise_retired_later_stays_readable_and_valid(
    service, user, retirable_exercise_id, test_engine
):
    plan = service.create_plan(
        user.id,
        WorkoutPlanCreate(
            name="Push Day", scheduled_date=DATE, exercises=[plan_exercise(retirable_exercise_id)]
        ),
    )

    retire_exercise(test_engine, retirable_exercise_id)

    read = service.get_plan(user.id, plan.id)
    assert [item.exercise_id for item in read.exercises] == [retirable_exercise_id]
    assert [p.id for p in service.list_plans(user.id, WorkoutPlanFilters())] == [plan.id]
    # its existing rules still apply unchanged: it can be planned
    service.update_plan(user.id, plan.id, WorkoutPlanUpdate(status="PLANNED"))
    assert stored_plan(test_engine, plan.id)["status"] == "PLANNED"
