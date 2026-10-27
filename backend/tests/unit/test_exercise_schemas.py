from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import Equipment, Exercise, ExerciseMuscle, MuscleGroup
from app.schemas import (
    Difficulty,
    ExerciseFilters,
    ExerciseResponse,
    ExerciseSource,
    MovementPattern,
    MuscleRole,
    WorkoutSection,
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
        # the database's defaults, which an unsaved exercise does not get
        "uses": ["MAIN_WORKOUT"],
        "image_paths": [],
        "source": "FORMIQ",
    }
    return Exercise(**{**fields, **overrides})


# an imported upstream record, as the dataset has it
UPSTREAM_RECORD = {
    "id": "Barbell_Bench_Press_-_Medium_Grip",
    "name": "Barbell Bench Press - Medium Grip",
    "force": "push",
    "level": "beginner",
    "mechanic": "compound",
    "equipment": "barbell",
    "primaryMuscles": ["chest"],
    "secondaryMuscles": ["shoulders", "triceps"],
    "instructions": ["Lie back on a flat bench.", "Lower the bar to the chest."],
    "category": "strength",
    "images": [
        "Barbell_Bench_Press_-_Medium_Grip/0.jpg",
        "Barbell_Bench_Press_-_Medium_Grip/1.jpg",
    ],
}


@pytest.mark.parametrize(
    ("enum", "values"),
    [
        (Difficulty, ["BEGINNER", "INTERMEDIATE", "ADVANCED", "UNRATED"]),
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
                "MOBILITY",
                "STRETCH",
                "CARDIO",
            ],
        ),
        (MuscleRole, ["PRIMARY", "SECONDARY"]),
        (WorkoutSection, ["WARM_UP", "MAIN_WORKOUT", "COOL_DOWN"]),
        (ExerciseSource, ["FORMIQ", "FREE_EXERCISE_DB", "EXERCISES_DATASET"]),
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
        # Formiq's own exercise: no upstream record, so no steps or category
        "instructions": [],
        "difficulty": "INTERMEDIATE",
        "movement_pattern": "HORIZONTAL_PUSH",
        "category": None,
        "uses": ["MAIN_WORKOUT"],
        "muscles": [
            {"id": 1, "name": "Chest", "role": "PRIMARY"},
            {"id": 8, "name": "Triceps", "role": "SECONDARY"},
        ],
        "equipment": [{"id": 1, "name": "Barbell"}, {"id": 4, "name": "Bench"}],
        "images": [],
        "source": "FORMIQ",
        "source_id": None,
        "source_version": None,
        "is_active": True,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_an_imported_exercise_shows_its_source_and_upstream_values_unchanged():
    exercise = make_exercise(
        id=812,
        movement_pattern=None,
        uses=["WARM_UP", "MAIN_WORKOUT"],
        image_paths=list(UPSTREAM_RECORD["images"]),
        source="FREE_EXERCISE_DB",
        source_id=UPSTREAM_RECORD["id"],
        source_version="f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5",
        source_record=UPSTREAM_RECORD,
    )

    response = ExerciseResponse.model_validate(exercise).model_dump(mode="json")

    # the upstream steps in order, and its category apart from Formiq's uses
    assert response["instructions"] == UPSTREAM_RECORD["instructions"]
    assert (response["category"], response["uses"]) == ("strength", ["WARM_UP", "MAIN_WORKOUT"])
    assert response["movement_pattern"] is None
    # the upstream id is kept apart from Formiq's id
    assert (response["id"], response["source"], response["source_id"]) == (
        812,
        "FREE_EXERCISE_DB",
        "Barbell_Bench_Press_-_Medium_Grip",
    )
    assert response["source_version"] == "f00c92c7dcf1216a928a52c3706c7ce8e2f71ed5"
    # images are API URLs, in order; the stored paths never reach a client
    assert response["images"] == [
        {"position": 0, "url": "/exercises/812/images/0"},
        {"position": 1, "url": "/exercises/812/images/1"},
    ]
    assert "jpg" not in str(response["images"])


def test_exercise_response_accepts_exercise_without_equipment():
    assert ExerciseResponse.model_validate(make_exercise(equipment=[])).equipment == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"difficulty": "EXPERT"},
        {"difficulty": "beginner"},
        {"movement_pattern": "PUSH"},
        {"muscles": [ExerciseMuscle(muscle_group=MuscleGroup(id=1, name="Chest"), role="MAIN")]},
        {"uses": ["MAIN"]},
        {"source": "WEB"},
    ],
)
def test_exercise_response_rejects_values_outside_the_enums(overrides):
    with pytest.raises(ValidationError):
        ExerciseResponse.model_validate(make_exercise(**overrides))


def test_exercise_filters_default_to_active_exercises_only():
    assert ExerciseFilters().model_dump() == {
        "difficulty": None,
        "movement_pattern": None,
        "use": None,
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
        {"use": "MAIN"},
        {"muscle_group_id": 0},
        {"muscle_group_id": 2_147_483_648},
        {"equipment_id": -1},
        {"equipment_id": 2_147_483_648},
    ],
)
def test_exercise_filters_reject_invalid_values(data):
    with pytest.raises(ValidationError):
        ExerciseFilters.model_validate(data)
