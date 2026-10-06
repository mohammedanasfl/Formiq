"""Integration tests for ExerciseCatalogService.

They require the local PostgreSQL container to be running. The service only
reads, so each test runs in a transaction that the db_session fixture rolls
back. The test database also holds the seeded catalog.
"""

import pytest

from app.schemas import ExerciseFilters
from app.services import ExerciseCatalogService
from tests.integration.catalog import (
    add_equipment,
    add_exercise,
    add_exercises_for_each_filter,
    add_muscle_group,
)


@pytest.fixture
def service(db_session):
    return ExerciseCatalogService(db_session)


def names(rows):
    return [row.name for row in rows]


@pytest.mark.parametrize(
    ("is_active", "expected"), [(True, "Test Match"), (False, "Test Inactive")]
)
def test_list_exercises_applies_every_filter(service, db_session, is_active, expected):
    muscle_group, item = add_exercises_for_each_filter(db_session)
    filters = ExerciseFilters(
        difficulty="BEGINNER",
        movement_pattern="SQUAT",
        muscle_group_id=muscle_group.id,
        equipment_id=item.id,
        is_active=is_active,
    )

    assert names(service.list_exercises(filters)) == [expected]


def test_list_exercises_returns_only_active_exercises_by_default(service, db_session):
    add_exercise(db_session, "Test Active")
    add_exercise(db_session, "Test Inactive", is_active=False)

    found = service.list_exercises(ExerciseFilters())

    assert "Test Active" in names(found)
    assert "Test Inactive" not in names(found)
    assert all(exercise.is_active for exercise in found)


def test_list_exercises_includes_the_seeded_catalog(service):
    found = names(service.list_exercises(ExerciseFilters()))

    assert {"Barbell Bench Press", "Push-Up", "Romanian Deadlift"} <= set(found)


def test_get_exercise_by_id_returns_the_exercise(service, db_session):
    muscle_group = add_muscle_group(db_session, "Test Muscle")
    exercise_id = add_exercise(db_session, "Test Exercise", primary=[muscle_group]).id
    db_session.expunge_all()

    exercise = service.get_exercise_by_id(exercise_id)

    assert exercise.name == "Test Exercise"
    assert [link.muscle_group.name for link in exercise.muscles] == ["Test Muscle"]


def test_get_exercise_by_id_returns_inactive_exercise(service, db_session):
    exercise_id = add_exercise(db_session, "Test Inactive", is_active=False).id

    assert service.get_exercise_by_id(exercise_id).is_active is False


def test_get_exercise_by_id_returns_none_for_missing_exercise(service):
    assert service.get_exercise_by_id(-1) is None


@pytest.mark.parametrize(
    ("list_rows", "add", "seeded"),
    [
        ("list_muscle_groups", add_muscle_group, "Chest"),
        ("list_equipment", add_equipment, "Barbell"),
    ],
)
def test_list_reference_data_filters_by_is_active(service, db_session, list_rows, add, seeded):
    add(db_session, "Test Inactive", is_active=False)

    active = names(getattr(service, list_rows)(is_active=True))
    inactive = names(getattr(service, list_rows)(is_active=False))

    assert seeded in active
    assert "Test Inactive" not in active
    assert inactive == ["Test Inactive"]
