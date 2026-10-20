"""The migration that adds the treadmill as equipment (c9e24b7a5d13).

They migrate the test database down and up again, and put it back at head. They require the
local PostgreSQL container, like the other migration tests.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Equipment, Exercise
from tests.migrations import ACTIVITIES_REVISION, TREADMILL_REVISION, migration_module


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


@pytest.fixture(scope="module")
def treadmill():
    return migration_module(TREADMILL_REVISION)


def equipment_named(engine, name):
    with Session(engine) as session:
        return session.scalars(select(Equipment).where(Equipment.name == name)).one_or_none()


def test_the_migration_follows_the_activities_and_there_is_one_head(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(TREADMILL_REVISION).down_revision == ACTIVITIES_REVISION
    assert script.get_heads() == [TREADMILL_REVISION]


def test_the_treadmill_is_active_equipment_with_a_description(
    alembic_config, test_engine, treadmill
):
    row = equipment_named(test_engine, "Treadmill")

    assert row.is_active
    assert row.description == treadmill.DESCRIPTION
    assert row.description == "A motorised belt for walking or running indoors."


def test_the_downgrade_removes_it_and_the_upgrade_adds_it_again(alembic_config, test_engine):
    command.downgrade(alembic_config, ACTIVITIES_REVISION)
    assert equipment_named(test_engine, "Treadmill") is None

    command.upgrade(alembic_config, "head")
    assert equipment_named(test_engine, "Treadmill") is not None


def test_the_upgrade_leaves_a_treadmill_the_catalog_already_has_as_it_is(
    alembic_config, test_engine
):
    """Equipment added by hand before: no second row, and nothing changed."""
    command.downgrade(alembic_config, ACTIVITIES_REVISION)
    with Session(test_engine) as session:
        session.add(Equipment(name="Treadmill", description="Mine."))
        session.commit()
    try:
        command.upgrade(alembic_config, "head")

        assert equipment_named(test_engine, "Treadmill").description == "Mine."
    finally:
        # the test database holds only the seeds: take the hand-made row out the way the
        # migration would, and put its own back
        command.downgrade(alembic_config, ACTIVITIES_REVISION)
        command.upgrade(alembic_config, "head")


def test_the_downgrade_gives_an_exercise_that_uses_it_the_machine_its_record_names(
    alembic_config, test_engine
):
    """An exercise linked to the treadmill by the import is linked to "Machine" again, so no
    exercise loses its equipment and the equipment can be deleted."""
    with Session(test_engine) as session:
        machine = session.scalars(select(Equipment).where(Equipment.name == "Machine")).one()
        treadmill = session.scalars(select(Equipment).where(Equipment.name == "Treadmill")).one()
        exercise = Exercise(
            name="QA Treadmill Jog", difficulty="BEGINNER", movement_pattern="CARDIO"
        )
        exercise.equipment = [treadmill]
        session.add(exercise)
        session.commit()
        exercise_id, machine_id = exercise.id, machine.id
    try:
        command.downgrade(alembic_config, ACTIVITIES_REVISION)

        assert equipment_named(test_engine, "Treadmill") is None
        with Session(test_engine) as session:
            kept = session.get(Exercise, exercise_id)
            assert [item.id for item in kept.equipment] == [machine_id]
    finally:
        command.upgrade(alembic_config, "head")
        with Session(test_engine) as session:
            session.query(Exercise).filter_by(id=exercise_id).delete()
            session.commit()
