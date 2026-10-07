from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import WorkoutPlan, WorkoutPlanExercise
from app.schemas import (
    WorkoutPlanCreate,
    WorkoutPlanExerciseCreate,
    WorkoutPlanExerciseUpdate,
    WorkoutPlanFilters,
    WorkoutPlanResponse,
    WorkoutPlanStatus,
    WorkoutPlanUpdate,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)

PLAN_EXERCISE = {
    "exercise_id": 1,
    "exercise_order": 1,
    "sets": 3,
    "reps": 8,
    "weight_kg": 50.0,
    "rest_seconds": 120,
    "notes": "Controlled tempo",
}

# Values that the plan exercise schemas reject, whether creating or updating.
INVALID_PLAN_EXERCISE_VALUES = [
    ("exercise_id", 0),
    ("exercise_id", 2_147_483_648),
    ("exercise_order", 0),
    ("exercise_order", -1),
    ("sets", 0),
    ("reps", 0),
    ("weight_kg", 0),
    ("weight_kg", -2.5),
    ("weight_kg", float("inf")),
    ("weight_kg", float("nan")),
    ("rest_seconds", -1),
    ("notes", ""),
    ("sets", "three"),
    # beyond the integer column; not a training limit
    ("reps", 2_147_483_648),
]


def test_status_values():
    assert [status.value for status in WorkoutPlanStatus] == ["DRAFT", "PLANNED", "CANCELLED"]


def test_plan_create_needs_only_a_name():
    plan = WorkoutPlanCreate.model_validate({"name": "Push Day"})

    assert plan.model_dump() == {
        "name": "Push Day",
        "description": None,
        "status": WorkoutPlanStatus.DRAFT,
        "scheduled_date": None,
        "exercises": [],
    }


def test_plan_create_accepts_every_field():
    plan = WorkoutPlanCreate.model_validate(
        {
            "name": "Push Day",
            "description": "Chest, shoulders and triceps",
            "status": "PLANNED",
            "scheduled_date": "2026-10-10",
            "exercises": [PLAN_EXERCISE],
        }
    )

    assert plan.status is WorkoutPlanStatus.PLANNED
    assert plan.scheduled_date == date(2026, 10, 10)
    assert [exercise.model_dump() for exercise in plan.exercises] == [PLAN_EXERCISE]


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"name": ""},
        {"name": "x" * 151},
        {"name": "Push Day", "description": ""},
        {"name": "Push Day", "status": "COMPLETED"},
        {"name": "Push Day", "status": "draft"},
        {"name": "Push Day", "scheduled_date": "10/10/2026"},
        {"name": "Push Day", "exercises": [{"exercise_id": 1, "exercise_order": 1}]},
    ],
)
def test_plan_create_rejects_invalid_data(data):
    with pytest.raises(ValidationError):
        WorkoutPlanCreate.model_validate(data)


@pytest.mark.parametrize("field", ["exercise_id", "exercise_order", "sets", "reps"])
def test_plan_exercise_create_requires_the_prescription(field):
    data = {key: value for key, value in PLAN_EXERCISE.items() if key != field}

    with pytest.raises(ValidationError):
        WorkoutPlanExerciseCreate.model_validate(data)


def test_plan_exercise_create_optional_fields_default_to_none():
    exercise = WorkoutPlanExerciseCreate(exercise_id=1, exercise_order=1, sets=3, reps=8)

    assert (exercise.weight_kg, exercise.rest_seconds, exercise.notes) == (None, None, None)


@pytest.mark.parametrize(("field", "value"), INVALID_PLAN_EXERCISE_VALUES)
def test_plan_exercise_create_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        WorkoutPlanExerciseCreate.model_validate({**PLAN_EXERCISE, field: value})


@pytest.mark.parametrize(("field", "value"), INVALID_PLAN_EXERCISE_VALUES)
def test_plan_exercise_update_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        WorkoutPlanExerciseUpdate.model_validate({field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("exercise_order", 1),
        ("sets", 1),
        ("reps", 1),
        ("weight_kg", 0.5),
        ("rest_seconds", 0),
        # no training maximum
        ("sets", 1_000),
        ("reps", 1_000),
        ("weight_kg", 1_000.0),
        ("weight_kg", None),
        ("rest_seconds", None),
        ("notes", None),
    ],
)
def test_plan_exercise_create_accepts_boundary_and_null_values(field, value):
    exercise = WorkoutPlanExerciseCreate.model_validate({**PLAN_EXERCISE, field: value})

    assert getattr(exercise, field) == value


@pytest.mark.parametrize(
    ("schema", "nullable_field"),
    [(WorkoutPlanUpdate, "scheduled_date"), (WorkoutPlanExerciseUpdate, "weight_kg")],
)
def test_updates_contain_only_the_supplied_fields(schema, nullable_field):
    assert schema.model_validate({}).model_dump(exclude_unset=True) == {}
    assert schema.model_validate({nullable_field: None}).model_dump(exclude_unset=True) == {
        nullable_field: None
    }


@pytest.mark.parametrize(
    "data",
    [
        {"name": ""},
        {"name": "x" * 151},
        {"description": ""},
        {"status": "COMPLETED"},
        {"scheduled_date": "tomorrow"},
    ],
)
def test_plan_update_rejects_invalid_values(data):
    with pytest.raises(ValidationError):
        WorkoutPlanUpdate.model_validate(data)


def test_update_fields_match_create_fields():
    # a plan's exercises are changed through their own routes, not the plan update
    assert set(WorkoutPlanUpdate.model_fields) == set(WorkoutPlanCreate.model_fields) - {
        "exercises"
    }
    assert set(WorkoutPlanExerciseUpdate.model_fields) == set(
        WorkoutPlanExerciseCreate.model_fields
    )


def test_plan_response_includes_the_plan_exercises():
    plan = WorkoutPlan(
        id=10,
        user_id=1,
        name="Push Day",
        description=None,
        status="PLANNED",
        scheduled_date=date(2026, 10, 10),
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
        exercises=[
            WorkoutPlanExercise(
                id=100,
                workout_plan_id=10,
                created_at=TIMESTAMP,
                updated_at=TIMESTAMP,
                **{**PLAN_EXERCISE, "notes": None},
            )
        ],
    )

    assert WorkoutPlanResponse.model_validate(plan).model_dump(mode="json") == {
        "id": 10,
        "user_id": 1,
        "name": "Push Day",
        "description": None,
        "status": "PLANNED",
        "scheduled_date": "2026-10-10",
        "exercises": [
            {
                "id": 100,
                "workout_plan_id": 10,
                "exercise_id": 1,
                "exercise_order": 1,
                "sets": 3,
                "reps": 8,
                "weight_kg": 50.0,
                "rest_seconds": 120,
                "notes": None,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            }
        ],
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_filters_default_to_every_plan_of_the_user():
    assert WorkoutPlanFilters().model_dump() == {"status": None, "scheduled_date": None}


@pytest.mark.parametrize("data", [{"status": "COMPLETED"}, {"scheduled_date": "2026-13-01"}])
def test_filters_reject_invalid_values(data):
    with pytest.raises(ValidationError):
        WorkoutPlanFilters.model_validate(data)
