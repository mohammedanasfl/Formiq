from datetime import date

import pytest

from app.models import WorkoutPlan, WorkoutPlanExercise
from app.schemas import WorkoutPlanExerciseCreate, WorkoutPlanExerciseUpdate, WorkoutPlanUpdate
from app.services.exceptions import (
    InvalidStatusTransitionError,
    InvalidWorkoutPlanError,
    WorkoutPlanNotEditableError,
)
from app.services.workout_plan_rules import (
    REQUIRED_PLAN_EXERCISE_FIELDS,
    REQUIRED_PLAN_FIELDS,
    check_editable,
    check_no_null_required_fields,
    check_planned_plan,
    check_status_change,
    check_unique_orders,
)

STATUSES = ["DRAFT", "PLANNED", "CANCELLED"]
ALLOWED = {
    ("DRAFT", "DRAFT"),
    ("DRAFT", "PLANNED"),
    ("DRAFT", "CANCELLED"),
    ("PLANNED", "PLANNED"),
    ("PLANNED", "CANCELLED"),
    ("CANCELLED", "CANCELLED"),
}
DATE = date(2026, 10, 10)


def not_null_columns(model):
    return {column.name for column in model.__table__.columns if not column.nullable}


def test_required_plan_fields_are_the_not_null_updatable_columns():
    assert REQUIRED_PLAN_FIELDS == not_null_columns(WorkoutPlan) & set(
        WorkoutPlanUpdate.model_fields
    )


def test_required_plan_exercise_fields_are_the_not_null_updatable_columns():
    assert REQUIRED_PLAN_EXERCISE_FIELDS == not_null_columns(WorkoutPlanExercise) & set(
        WorkoutPlanExerciseUpdate.model_fields
    )


@pytest.mark.parametrize("current", STATUSES)
@pytest.mark.parametrize("new", STATUSES)
def test_status_changes(current, new):
    if (current, new) in ALLOWED:
        check_status_change(current, new)
    else:
        with pytest.raises(
            InvalidStatusTransitionError, match=f"a {current} .* cannot become {new}"
        ):
            check_status_change(current, new)


@pytest.mark.parametrize("status", ["DRAFT", "PLANNED"])
def test_draft_and_planned_plans_are_editable(status):
    check_editable(WorkoutPlan(id=1, status=status))


def test_cancelled_plan_is_not_editable():
    with pytest.raises(WorkoutPlanNotEditableError):
        check_editable(WorkoutPlan(id=1, status="CANCELLED"))


@pytest.mark.parametrize(
    ("status", "scheduled_date", "exercise_count"),
    [
        ("DRAFT", None, 0),
        ("CANCELLED", None, 0),
        ("PLANNED", DATE, 1),
        ("PLANNED", DATE, 5),
    ],
)
def test_valid_plans(status, scheduled_date, exercise_count):
    check_planned_plan(status, scheduled_date, exercise_count)


@pytest.mark.parametrize(
    ("scheduled_date", "exercise_count", "message"),
    [
        (None, 1, "needs a scheduled_date"),
        (DATE, 0, "needs at least one exercise"),
        (None, 0, "needs a scheduled_date"),
    ],
)
def test_planned_plan_needs_a_date_and_an_exercise(scheduled_date, exercise_count, message):
    with pytest.raises(InvalidWorkoutPlanError, match=message):
        check_planned_plan("PLANNED", scheduled_date, exercise_count)


def test_null_is_rejected_only_for_required_fields():
    check_no_null_required_fields({"description": None, "name": "Push Day"}, REQUIRED_PLAN_FIELDS)

    with pytest.raises(InvalidWorkoutPlanError, match="cannot be null: name, status"):
        check_no_null_required_fields({"status": None, "name": None}, REQUIRED_PLAN_FIELDS)


def plan_exercise(exercise_order, exercise_id=1):
    return WorkoutPlanExerciseCreate(
        exercise_id=exercise_id, exercise_order=exercise_order, sets=3, reps=8
    )


def test_exercise_orders_must_be_unique_but_exercises_may_repeat():
    check_unique_orders([plan_exercise(1), plan_exercise(2), plan_exercise(3, exercise_id=1)])

    with pytest.raises(InvalidWorkoutPlanError, match="once in a workout plan: 1, 3$"):
        check_unique_orders([plan_exercise(order) for order in [1, 3, 2, 1, 3]])
