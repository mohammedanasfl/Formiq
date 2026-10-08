"""Integration tests for the exercise catalog models and database constraints.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

import pytest
from psycopg.errors import ForeignKeyViolation, RestrictViolation, UniqueViolation
from sqlalchemy import delete, func, insert, select
from sqlalchemy.exc import IntegrityError

from app.models import Equipment, Exercise, ExerciseMuscle, MuscleGroup, exercise_equipment
from tests.integration.catalog import add_equipment, add_exercise, add_muscle_group


@pytest.fixture
def muscle_groups(db_session):
    return [add_muscle_group(db_session, f"Test Muscle {letter}") for letter in "ABC"]


@pytest.fixture
def equipment(db_session):
    return [add_equipment(db_session, f"Test Equipment {letter}") for letter in "AB"]


def count_links(session, table, exercise_id):
    return session.scalar(
        select(func.count()).select_from(table).where(table.c.exercise_id == exercise_id)
    )


def test_exercise_has_primary_and_secondary_muscles_and_several_equipment_items(
    db_session, muscle_groups, equipment
):
    a, b, c = muscle_groups
    exercise_id = add_exercise(
        db_session, "Test Exercise", primary=[a], secondary=[b, c], equipment=equipment
    ).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    exercise = db_session.get(Exercise, exercise_id)

    assert [(link.muscle_group.name, link.role) for link in exercise.muscles] == [
        ("Test Muscle A", "PRIMARY"),
        ("Test Muscle B", "SECONDARY"),
        ("Test Muscle C", "SECONDARY"),
    ]
    assert all(link.exercise is exercise for link in exercise.muscles)
    assert [item.name for item in exercise.equipment] == ["Test Equipment A", "Test Equipment B"]


def test_exercise_can_need_no_equipment(db_session, muscle_groups):
    exercise_id = add_exercise(db_session, "Test Bodyweight", primary=muscle_groups[:1]).id
    db_session.expunge_all()

    exercise = db_session.get(Exercise, exercise_id)

    assert exercise.equipment == []
    assert count_links(db_session, exercise_equipment, exercise_id) == 0


@pytest.mark.parametrize(
    ("model", "values"),
    [
        (
            Exercise,
            {"name": "Test Defaults", "difficulty": "BEGINNER", "movement_pattern": "SQUAT"},
        ),
        (MuscleGroup, {"name": "Test Defaults"}),
        (Equipment, {"name": "Test Defaults"}),
    ],
)
def test_catalog_rows_are_active_and_timestamped_by_default(db_session, model, values):
    # is_active and the timestamps are left to the database defaults
    row_id = db_session.execute(insert(model).values(**values).returning(model.id)).scalar_one()

    stored = db_session.get(model, row_id)

    assert stored.is_active is True
    assert stored.created_at is not None
    assert stored.updated_at is not None


@pytest.mark.parametrize(
    "add",
    [
        lambda session: add_exercise(session, "Test Duplicate"),
        lambda session: add_muscle_group(session, "Test Duplicate"),
        lambda session: add_equipment(session, "Test Duplicate"),
    ],
    ids=["exercise", "muscle_group", "equipment"],
)
def test_names_are_unique(db_session, add):
    add(db_session)

    with pytest.raises(IntegrityError) as error:
        add(db_session)

    assert isinstance(error.value.orig, UniqueViolation)


def test_exercise_cannot_have_the_same_muscle_group_twice(db_session, muscle_groups):
    a = muscle_groups[0]
    exercise = add_exercise(db_session, "Test Exercise", primary=[a])

    # even with another role: an exercise and a muscle group are linked only once
    with pytest.raises(IntegrityError) as error:
        db_session.execute(
            insert(ExerciseMuscle).values(
                exercise_id=exercise.id, muscle_group_id=a.id, role="SECONDARY"
            )
        )

    assert isinstance(error.value.orig, UniqueViolation)


def test_exercise_cannot_have_the_same_equipment_twice(db_session, equipment):
    item = equipment[0]
    exercise = add_exercise(db_session, "Test Exercise", equipment=[item])

    with pytest.raises(IntegrityError) as error:
        db_session.execute(
            insert(exercise_equipment).values(exercise_id=exercise.id, equipment_id=item.id)
        )

    assert isinstance(error.value.orig, UniqueViolation)


@pytest.mark.parametrize(
    ("table", "missing"),
    [
        (ExerciseMuscle.__table__, "exercise_id"),
        (ExerciseMuscle.__table__, "muscle_group_id"),
        (exercise_equipment, "exercise_id"),
        (exercise_equipment, "equipment_id"),
    ],
)
def test_links_must_reference_existing_rows(db_session, muscle_groups, equipment, table, missing):
    exercise = add_exercise(db_session, "Test Exercise")
    values = {"exercise_id": exercise.id}
    if table is exercise_equipment:
        values["equipment_id"] = equipment[0].id
    else:
        values |= {"muscle_group_id": muscle_groups[0].id, "role": "PRIMARY"}
    values[missing] = -1  # no row has this id

    with pytest.raises(IntegrityError) as error:
        db_session.execute(insert(table).values(**values))

    assert isinstance(error.value.orig, ForeignKeyViolation)


def test_deleting_an_exercise_deletes_its_links_only(db_session, muscle_groups, equipment):
    exercise_id = add_exercise(
        db_session, "Test Exercise", primary=muscle_groups, equipment=equipment
    ).id

    db_session.execute(delete(Exercise).where(Exercise.id == exercise_id))

    assert count_links(db_session, ExerciseMuscle.__table__, exercise_id) == 0
    assert count_links(db_session, exercise_equipment, exercise_id) == 0
    for row in [*muscle_groups, *equipment]:
        db_session.refresh(row)  # still in the database


@pytest.mark.parametrize("model", [MuscleGroup, Equipment])
def test_muscle_group_or_equipment_used_by_an_exercise_cannot_be_deleted(
    db_session, muscle_groups, equipment, model
):
    add_exercise(db_session, "Test Exercise", primary=muscle_groups, equipment=equipment)
    used = muscle_groups[0] if model is MuscleGroup else equipment[0]

    with pytest.raises(IntegrityError) as error:
        db_session.execute(delete(model).where(model.id == used.id))

    # raised by ON DELETE RESTRICT
    assert isinstance(error.value.orig, RestrictViolation)
