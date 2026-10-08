"""Integration tests for the exercise catalog repositories.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back. The test database also
holds the seeded catalog, so the tests either filter down to their own data or
check the results without assuming the catalog is empty.
"""

from contextlib import contextmanager

import pytest
from sqlalchemy import event

from app.repositories import EquipmentRepository, ExerciseRepository, MuscleGroupRepository
from tests.integration.catalog import add_equipment, add_exercise, add_muscle_group


@pytest.fixture
def exercises(db_session):
    return ExerciseRepository(db_session)


@pytest.fixture
def muscle_a(db_session):
    return add_muscle_group(db_session, "Test Muscle A")


@pytest.fixture
def muscle_b(db_session):
    return add_muscle_group(db_session, "Test Muscle B")


@pytest.fixture
def equipment_a(db_session):
    return add_equipment(db_session, "Test Equipment A")


def names(found):
    return [exercise.name for exercise in found]


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


def test_get_by_id_returns_exercise_with_muscles_and_equipment(
    exercises, db_session, muscle_a, muscle_b, equipment_a
):
    exercise_id = add_exercise(
        db_session,
        "Test Exercise",
        primary=[muscle_b],
        secondary=[muscle_a],
        equipment=[equipment_a],
    ).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    exercise = exercises.get_by_id(exercise_id)

    assert exercise.name == "Test Exercise"
    # primary muscles first
    assert [(link.muscle_group.name, link.role) for link in exercise.muscles] == [
        ("Test Muscle B", "PRIMARY"),
        ("Test Muscle A", "SECONDARY"),
    ]
    assert [item.name for item in exercise.equipment] == ["Test Equipment A"]


def test_get_by_id_returns_inactive_exercise(exercises, db_session):
    exercise_id = add_exercise(db_session, "Test Inactive", is_active=False).id
    db_session.expunge_all()

    assert exercises.get_by_id(exercise_id).is_active is False


def test_get_by_id_returns_none_for_missing_exercise(exercises):
    assert exercises.get_by_id(-1) is None


def test_find_returns_exercises_ordered_by_name(exercises, db_session, muscle_a):
    for name in ["Test Zeta", "Test Alpha", "Test Mu"]:
        add_exercise(db_session, name, primary=[muscle_a])

    assert names(exercises.find(muscle_group_id=muscle_a.id)) == [
        "Test Alpha",
        "Test Mu",
        "Test Zeta",
    ]


def test_find_without_filters_returns_active_and_inactive_exercises(exercises, db_session):
    add_exercise(db_session, "Test Active")
    add_exercise(db_session, "Test Inactive", is_active=False)

    assert {"Test Active", "Test Inactive"} <= set(names(exercises.find()))


@pytest.mark.parametrize("is_active", [True, False])
def test_find_filters_by_is_active(exercises, db_session, is_active):
    add_exercise(db_session, "Test Active")
    add_exercise(db_session, "Test Inactive", is_active=False)

    found = exercises.find(is_active=is_active)

    assert all(exercise.is_active is is_active for exercise in found)
    assert ("Test Active" if is_active else "Test Inactive") in names(found)


@pytest.mark.parametrize(
    ("field", "value", "other_value"),
    [
        ("difficulty", "ADVANCED", "BEGINNER"),
        ("movement_pattern", "HINGE", "SQUAT"),
    ],
)
def test_find_filters_by_difficulty_and_movement_pattern(
    exercises, db_session, field, value, other_value
):
    add_exercise(db_session, "Test Match", **{field: value})
    add_exercise(db_session, "Test Other", **{field: other_value})

    found = exercises.find(**{field: value})

    assert all(getattr(exercise, field) == value for exercise in found)
    assert "Test Match" in names(found)
    assert "Test Other" not in names(found)


def test_find_by_muscle_group_matches_primary_and_secondary_muscles(
    exercises, db_session, muscle_a, muscle_b
):
    add_exercise(db_session, "Test Primary", primary=[muscle_a])
    add_exercise(db_session, "Test Secondary", primary=[muscle_b], secondary=[muscle_a])
    add_exercise(db_session, "Test Other Muscle", primary=[muscle_b])

    assert names(exercises.find(muscle_group_id=muscle_a.id)) == ["Test Primary", "Test Secondary"]


def test_find_by_equipment_matches_exercises_that_need_it(exercises, db_session, equipment_a):
    other = add_equipment(db_session, "Test Equipment B")
    add_exercise(db_session, "Test Needs A", equipment=[equipment_a, other])
    add_exercise(db_session, "Test Needs B", equipment=[other])
    add_exercise(db_session, "Test No Equipment")

    assert names(exercises.find(equipment_id=equipment_a.id)) == ["Test Needs A"]


def test_find_with_unknown_muscle_group_or_equipment_returns_nothing(exercises):
    assert exercises.find(muscle_group_id=-1) == []
    assert exercises.find(equipment_id=-1) == []


@pytest.mark.parametrize("load", ["find", "get_by_id"])
def test_relationships_load_in_a_fixed_number_of_queries(
    exercises, db_session, test_engine, muscle_a, muscle_b, equipment_a, load
):
    equipment_b = add_equipment(db_session, "Test Equipment B")
    ids = [
        add_exercise(
            db_session,
            f"Test Exercise {number}",
            primary=[muscle_a],
            secondary=[muscle_b],
            equipment=[equipment_a, equipment_b],
        ).id
        for number in range(3)
    ]
    db_session.expunge_all()

    with count_queries(test_engine) as statements:
        found = exercises.find() if load == "find" else [exercises.get_by_id(ids[0])]
        loaded = {
            exercise.name: (
                [(link.muscle_group.name, link.role) for link in exercise.muscles],
                [item.name for item in exercise.equipment],
            )
            for exercise in found
        }

    # the exercises, their muscles with the muscle groups, and their equipment:
    # three queries however many exercises there are
    assert len(statements) == 3
    assert loaded["Test Exercise 0"] == (
        [("Test Muscle A", "PRIMARY"), ("Test Muscle B", "SECONDARY")],
        ["Test Equipment A", "Test Equipment B"],
    )


@pytest.mark.parametrize(
    ("repository_class", "add"),
    [(MuscleGroupRepository, add_muscle_group), (EquipmentRepository, add_equipment)],
)
def test_reference_data_find_orders_by_name_and_filters_by_is_active(
    db_session, repository_class, add
):
    add(db_session, "Test B", is_active=False)
    add(db_session, "Test A", is_active=False)
    repository = repository_class(db_session)

    active = repository.find(is_active=True)
    inactive = repository.find(is_active=False)

    assert active  # the seeded reference data
    assert all(row.is_active for row in active)
    assert [row.name for row in inactive] == ["Test A", "Test B"]
    assert len(repository.find()) == len(active) + len(inactive)
