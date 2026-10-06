from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import Equipment, Exercise, ExerciseMuscle, MuscleGroup
from app.schemas import (
    Difficulty,
    ExerciseFilters,
    ExerciseResponse,
    MovementPattern,
    MuscleRole,
)

TIMESTAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_exercise(**overrides):
    chest = MuscleGroup(id=1, name="Chest")
    triceps = MuscleGroup(id=8, name="Triceps")
    fields = {
        "id": 3,
        "name": "Barbell Bench Press",
        "description": None,
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        "is_active": True,
        "created_at": TIMESTAMP,
        "updated_at": TIMESTAMP,
        "muscles": [
            ExerciseMuscle(muscle_group=chest, role="PRIMARY"),
            ExerciseMuscle(muscle_group=triceps, role="SECONDARY"),
        ],
        "equipment": [Equipment(id=1, name="Barbell"), Equipment(id=4, name="Bench")],
    }
    return Exercise(**{**fields, **overrides})


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (Difficulty, ["BEGINNER", "INTERMEDIATE", "ADVANCED"]),
        (
            MovementPattern,
            [
                "HORIZONTAL_PUSH",
                "HORIZONTAL_PULL",
                "VERTICAL_PUSH",
                "VERTICAL_PULL",
                "SQUAT",
                "HINGE",
                "LUNGE",
                "CARRY",
                "ROTATION",
                "ISOLATION",
            ],
        ),
        (MuscleRole, ["PRIMARY", "SECONDARY"]),
    ],
)
def test_enums_have_the_allowed_values(enum, values):
    assert [member.value for member in enum] == values


def test_exercise_response_flattens_muscles_and_equipment():
    response = ExerciseResponse.model_validate(make_exercise())

    assert response.model_dump(mode="json") == {
        "id": 3,
        "name": "Barbell Bench Press",
        "description": None,
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        "muscles": [
            {"id": 1, "name": "Chest", "role": "PRIMARY"},
            {"id": 8, "name": "Triceps", "role": "SECONDARY"},
        ],
        "equipment": [{"id": 1, "name": "Barbell"}, {"id": 4, "name": "Bench"}],
        "is_active": True,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_exercise_response_accepts_exercise_without_equipment():
    assert ExerciseResponse.model_validate(make_exercise(equipment=[])).equipment == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"difficulty": "EXPERT"},
        {"difficulty": "beginner"},
        {"movement_pattern": "PUSH"},
        {"muscles": [ExerciseMuscle(muscle_group=MuscleGroup(id=1, name="Chest"), role="MAIN")]},
    ],
)
def test_exercise_response_rejects_values_outside_the_enums(overrides):
    with pytest.raises(ValidationError):
        ExerciseResponse.model_validate(make_exercise(**overrides))


def test_exercise_filters_default_to_active_exercises_only():
    assert ExerciseFilters().model_dump() == {
        "difficulty": None,
        "movement_pattern": None,
        "muscle_group_id": None,
        "equipment_id": None,
        "is_active": True,
    }


@pytest.mark.parametrize(
    "data",
    [
        {"difficulty": "EXPERT"},
        {"difficulty": "beginner"},
        {"movement_pattern": "PUSH"},
        {"muscle_group_id": 0},
        {"muscle_group_id": 2_147_483_648},
        {"equipment_id": -1},
        {"equipment_id": 2_147_483_648},
    ],
)
def test_exercise_filters_reject_invalid_values(data):
    with pytest.raises(ValidationError):
        ExerciseFilters.model_validate(data)
