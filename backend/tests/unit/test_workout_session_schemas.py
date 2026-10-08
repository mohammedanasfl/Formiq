from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import WorkoutSession, WorkoutSessionExercise, WorkoutSet
from app.schemas import (
    WorkoutSessionCreate,
    WorkoutSessionExerciseCreate,
    WorkoutSessionExerciseUpdate,
    WorkoutSessionFilters,
    WorkoutSessionResponse,
    WorkoutSessionStatus,
    WorkoutSessionUpdate,
    WorkoutSetCreate,
    WorkoutSetUpdate,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)

SET = {
    "set_number": 1,
    "reps": 8,
    "weight_kg": 50.0,
    "rpe": 8.5,
    "completed": True,
    "notes": "Last rep slow",
}

# Values that the set schemas reject, whether creating or updating.
INVALID_SET_VALUES = [
    ("set_number", 0),
    ("set_number", -1),
    ("reps", 0),
    ("weight_kg", 0),
    ("weight_kg", -20.0),
    ("weight_kg", float("inf")),
    ("weight_kg", float("nan")),
    ("rpe", 0),
    ("rpe", 0.5),
    ("rpe", 10.5),
    ("rpe", 11),
    ("rpe", float("inf")),
    ("rpe", float("nan")),
    ("completed", "maybe"),
    ("notes", ""),
    # beyond the integer column; not a training limit
    ("reps", 2_147_483_648),
]

# Values that the session exercise schemas reject, whether creating or updating.
INVALID_SESSION_EXERCISE_VALUES = [
    ("exercise_id", 0),
    ("exercise_id", "bench"),
    ("exercise_order", 0),
    ("plan_exercise_id", 0),
    ("plan_exercise_id", 2_147_483_648),
    ("notes", ""),
]


def test_status_values():
    assert [status.value for status in WorkoutSessionStatus] == [
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    ]


def test_session_create_accepts_a_manual_or_planned_workout():
    assert WorkoutSessionCreate.model_validate({}).model_dump() == {
        "workout_plan_id": None,
        "notes": None,
    }
    assert WorkoutSessionCreate.model_validate({"workout_plan_id": 10}).workout_plan_id == 10


def test_session_create_takes_no_status_or_timestamps():
    # a session always starts IN_PROGRESS, at a time the database sets
    assert set(WorkoutSessionCreate.model_fields) == {"workout_plan_id", "notes"}


@pytest.mark.parametrize(
    "data", [{"workout_plan_id": 0}, {"workout_plan_id": "plan"}, {"notes": ""}]
)
def test_session_create_rejects_invalid_values(data):
    with pytest.raises(ValidationError):
        WorkoutSessionCreate.model_validate(data)


def test_session_update_changes_only_status_and_notes():
    assert set(WorkoutSessionUpdate.model_fields) == {"status", "notes"}
    assert WorkoutSessionUpdate.model_validate({}).model_dump(exclude_unset=True) == {}
    assert WorkoutSessionUpdate.model_validate({"notes": None}).model_dump(exclude_unset=True) == {
        "notes": None
    }


@pytest.mark.parametrize("data", [{"status": "PLANNED"}, {"status": "completed"}, {"notes": ""}])
def test_session_update_rejects_invalid_values(data):
    with pytest.raises(ValidationError):
        WorkoutSessionUpdate.model_validate(data)


@pytest.mark.parametrize("field", ["exercise_id", "exercise_order"])
def test_session_exercise_create_requires_exercise_and_order(field):
    data = {"exercise_id": 1, "exercise_order": 1}
    del data[field]

    with pytest.raises(ValidationError):
        WorkoutSessionExerciseCreate.model_validate(data)


def test_session_exercise_create_link_and_notes_are_optional():
    exercise = WorkoutSessionExerciseCreate(exercise_id=1, exercise_order=1)

    assert (exercise.plan_exercise_id, exercise.notes) == (None, None)


@pytest.mark.parametrize(("field", "value"), INVALID_SESSION_EXERCISE_VALUES)
def test_session_exercise_schemas_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        WorkoutSessionExerciseCreate.model_validate(
            {"exercise_id": 1, "exercise_order": 1, field: value}
        )
    with pytest.raises(ValidationError):
        WorkoutSessionExerciseUpdate.model_validate({field: value})


@pytest.mark.parametrize("field", ["set_number", "reps"])
def test_set_create_requires_set_number_and_reps(field):
    data = {key: value for key, value in SET.items() if key != field}

    with pytest.raises(ValidationError):
        WorkoutSetCreate.model_validate(data)


def test_set_create_defaults_to_a_completed_set_without_details():
    workout_set = WorkoutSetCreate(set_number=1, reps=8)

    assert workout_set.model_dump() == {
        "set_number": 1,
        "reps": 8,
        "weight_kg": None,
        "rpe": None,
        "completed": True,
        "notes": None,
    }


@pytest.mark.parametrize(("field", "value"), INVALID_SET_VALUES)
def test_set_schemas_reject_invalid_values(field, value):
    with pytest.raises(ValidationError):
        WorkoutSetCreate.model_validate({**SET, field: value})
    with pytest.raises(ValidationError):
        WorkoutSetUpdate.model_validate({field: value})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("rpe", 1),
        ("rpe", 10),
        ("rpe", 7.5),
        ("weight_kg", 0.5),
        ("completed", False),
        # no training maximum
        ("reps", 1_000),
        ("weight_kg", 1_000.0),
        ("weight_kg", None),
        ("rpe", None),
        ("notes", None),
    ],
)
def test_set_create_accepts_boundary_and_null_values(field, value):
    assert getattr(WorkoutSetCreate.model_validate({**SET, field: value}), field) == value


def test_update_fields_match_create_fields():
    assert set(WorkoutSetUpdate.model_fields) == set(WorkoutSetCreate.model_fields)
    assert set(WorkoutSessionExerciseUpdate.model_fields) == set(
        WorkoutSessionExerciseCreate.model_fields
    )


def test_session_response_nests_exercises_and_sets():
    workout_session = WorkoutSession(
        id=5,
        user_id=1,
        workout_plan_id=None,
        status="COMPLETED",
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
        notes=None,
        created_at=TIMESTAMP,
        updated_at=TIMESTAMP,
        exercises=[
            WorkoutSessionExercise(
                id=50,
                workout_session_id=5,
                plan_exercise_id=None,
                exercise_id=1,
                exercise_order=1,
                notes=None,
                created_at=TIMESTAMP,
                updated_at=TIMESTAMP,
                sets=[
                    WorkoutSet(
                        id=500,
                        workout_session_exercise_id=50,
                        created_at=TIMESTAMP,
                        updated_at=TIMESTAMP,
                        **SET,
                    )
                ],
            )
        ],
    )

    stamp = "2026-01-01T00:00:00Z"
    assert WorkoutSessionResponse.model_validate(workout_session).model_dump(mode="json") == {
        "id": 5,
        "user_id": 1,
        "workout_plan_id": None,
        "status": "COMPLETED",
        "started_at": stamp,
        "completed_at": stamp,
        "notes": None,
        "exercises": [
            {
                "id": 50,
                "workout_session_id": 5,
                "plan_exercise_id": None,
                "exercise_id": 1,
                "exercise_order": 1,
                "notes": None,
                "sets": [
                    {
                        "id": 500,
                        "workout_session_exercise_id": 50,
                        **SET,
                        "created_at": stamp,
                        "updated_at": stamp,
                    }
                ],
                "created_at": stamp,
                "updated_at": stamp,
            }
        ],
        "created_at": stamp,
        "updated_at": stamp,
    }


def test_filters_default_to_every_session_of_the_user():
    assert WorkoutSessionFilters().model_dump() == {"status": None}
