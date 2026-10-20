"""The migration that adds Formiq's warm-up and cool-down activities and says how to do the
existing ones (a7d3f1c82e4b): what it adds, that it changes no id and nothing a person edited,
that it refuses a name the catalog already has, and that a saved plan survives it either way.

They migrate the test database down and up again, and put it back at head. They require the
local PostgreSQL container to be running.
"""

import pytest
from alembic import command
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Exercise, User, WorkoutPlan, WorkoutPlanExercise
from app.repositories.exercise_repository import LOAD_MUSCLES_AND_EQUIPMENT
from app.schemas import ExerciseResponse
from tests.migrations import (
    ACTIVITIES_REVISION,
    TREADMILL_REVISION,
    LATER_SEED_REVISION,
    PROPOSALS_REVISION,
    SEED_REVISION,
    migration_module,
)


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


@pytest.fixture(scope="module")
def activities():
    return migration_module(ACTIVITIES_REVISION)


@pytest.fixture(scope="module")
def seed():
    return migration_module(SEED_REVISION)


@pytest.fixture(scope="module")
def later_seed():
    return migration_module(LATER_SEED_REVISION)


def new_text(activities, name):
    """What the migration makes of an existing activity's description."""
    return f"{activities.OLD_DESCRIPTIONS[name]} {activities.ADDITIONS[name]}"


def formiqs_exercises(session):
    """Formiq's own exercises by name, with what the migration could change."""
    exercises = session.scalars(
        select(Exercise).options(*LOAD_MUSCLES_AND_EQUIPMENT).where(Exercise.source == "FORMIQ")
    ).all()
    return {
        exercise.name: {
            "id": exercise.id,
            "description": exercise.description,
            "difficulty": exercise.difficulty,
            "movement_pattern": exercise.movement_pattern,
            "uses": list(exercise.uses),
            "muscles": {link.muscle_group.name: link.role for link in exercise.muscles},
            "equipment": sorted(item.name for item in exercise.equipment),
        }
        for exercise in exercises
    }


def current_revision(engine):
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def test_the_migration_follows_the_proposals_table_and_there_is_one_head(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(ACTIVITIES_REVISION).down_revision == PROPOSALS_REVISION
    assert len(script.get_heads()) == 1


def test_the_activities_are_added_with_their_muscles_equipment_and_sections(
    alembic_config, db_session, activities
):
    found = formiqs_exercises(db_session)

    assert len(activities.NEW_ACTIVITIES) == 21
    for activity in activities.NEW_ACTIVITIES:
        row = found[activity["name"]]
        assert row["description"] == activity["description"], activity["name"]
        assert row["difficulty"] == "BEGINNER", activity["name"]
        assert row["movement_pattern"] == activity["movement_pattern"], activity["name"]
        assert row["uses"] == activity["uses"], activity["name"]
        assert row["muscles"] == activity["muscles"], activity["name"]
        assert row["equipment"] == sorted(activity["equipment"]), activity["name"]
    stored = db_session.scalars(
        select(Exercise).where(Exercise.name.in_([a["name"] for a in activities.NEW_ACTIVITIES]))
    ).all()
    for exercise in stored:
        # Formiq's own: no source record, no images, active
        assert (exercise.source, exercise.source_id, exercise.source_record) == (
            "FORMIQ",
            None,
            None,
        )
        assert exercise.image_paths == [] and exercise.is_active
        ExerciseResponse.model_validate(exercise)


def test_the_existing_activities_only_gain_a_dose_and_a_safety_note(
    alembic_config, db_session, activities, seed, later_seed
):
    found = formiqs_exercises(db_session)
    written = {a["name"]: a for a in later_seed.STRENGTH_EXERCISES + later_seed.ACTIVITIES}

    assert len(activities.OLD_DESCRIPTIONS) == 26
    for name in activities.OLD_DESCRIPTIONS:
        row = found[name]
        assert row["description"] == new_text(activities, name), name
        assert row["description"].startswith(written[name]["description"]), name
        # nothing else about it
        assert row["movement_pattern"] == written[name]["movement_pattern"], name
        assert row["muscles"] == written[name]["muscles"], name
        assert row["equipment"] == sorted(written[name]["equipment"]), name
    # a Formiq exercise that is no warm-up or cool-down is not touched
    bench = next(a for a in seed.EXERCISES if a["name"] == "Barbell Bench Press")
    assert found["Barbell Bench Press"]["description"] == bench["description"]


def test_the_downgrade_and_the_upgrade_again_change_no_id_and_restore_the_catalog(
    alembic_config, test_engine, db_session, activities, later_seed
):
    before = formiqs_exercises(db_session)
    db_session.close()
    new_names = {a["name"] for a in activities.NEW_ACTIVITIES}

    command.downgrade(alembic_config, PROPOSALS_REVISION)
    with Session(test_engine) as session:
        down = formiqs_exercises(session)
    assert set(down) == set(before) - new_names
    assert len(down) == 50
    for name, old in activities.OLD_DESCRIPTIONS.items():
        assert down[name]["description"] == old, name
        assert down[name]["id"] == before[name]["id"], name

    command.upgrade(alembic_config, "head")
    with Session(test_engine) as session:
        up = formiqs_exercises(session)
    assert set(up) == set(before)
    # the exercises that were there keep their ids, so plans and sessions that use them still do
    for name in set(before) - new_names:
        assert up[name] == before[name], name


def test_a_description_edited_since_is_left_alone(alembic_config, test_engine, activities):
    command.downgrade(alembic_config, PROPOSALS_REVISION)
    with Session(test_engine) as session:
        session.execute(
            Exercise.__table__.update()
            .where(Exercise.name == "Cat-Cow")
            .values(description="Edited by hand.")
        )
        session.commit()
    try:
        command.upgrade(alembic_config, "head")
        with Session(test_engine) as session:
            found = formiqs_exercises(session)
        assert found["Cat-Cow"]["description"] == "Edited by hand."
        assert found["Arm Circles"]["description"] == new_text(activities, "Arm Circles")
    finally:
        with Session(test_engine) as session:
            session.execute(
                Exercise.__table__.update()
                .where(Exercise.name == "Cat-Cow")
                .values(description=new_text(activities, "Cat-Cow"))
            )
            session.commit()


def test_a_name_the_catalog_already_has_stops_the_upgrade_and_changes_nothing(
    alembic_config, test_engine, activities
):
    command.downgrade(alembic_config, PROPOSALS_REVISION)
    with Session(test_engine) as session:
        session.add(
            Exercise(
                name="Wall Push-Up",
                difficulty="BEGINNER",
                movement_pattern=None,
                source="FREE_EXERCISE_DB",
                source_id="Test_Wall_Push_Up",
                source_record={"id": "Test_Wall_Push_Up"},
            )
        )
        session.commit()
    try:
        with pytest.raises(RuntimeError, match="already has exercises named"):
            command.upgrade(alembic_config, "head")

        assert current_revision(test_engine) == PROPOSALS_REVISION
        with Session(test_engine) as session:
            found = formiqs_exercises(session)
            other = session.scalars(select(Exercise).where(Exercise.name == "Wall Push-Up")).one()
            # the migration did not attach its muscles to the exercise that has the name
            assert other.muscles == [] and other.source_id == "Test_Wall_Push_Up"
        assert not {a["name"] for a in activities.NEW_ACTIVITIES} & set(found)
        assert found["Arm Circles"]["description"] == activities.OLD_DESCRIPTIONS["Arm Circles"]
    finally:
        with Session(test_engine) as session:
            session.execute(
                Exercise.__table__.delete().where(Exercise.source_id == "Test_Wall_Push_Up")
            )
            session.commit()


def plan_with(session, email, names):
    """A user's plan whose warm-up holds the named exercises, committed."""
    user = User(email=email)
    session.add(user)
    session.flush()
    plan = WorkoutPlan(user_id=user.id, name="Saved plan", status="PLANNED")
    session.add(plan)
    session.flush()
    for order, name in enumerate(names, start=1):
        exercise_id = session.scalars(select(Exercise.id).where(Exercise.name == name)).one()
        session.add(
            WorkoutPlanExercise(
                workout_plan_id=plan.id,
                exercise_id=exercise_id,
                exercise_order=order,
                section="WARM_UP",
                sets=1,
                reps=8,
            )
        )
    session.commit()
    return plan.id


def plan_rows(engine, plan_id):
    with Session(engine) as session:
        return [
            (row.exercise_id, row.exercise_order, row.section, row.exercise.name)
            for row in session.scalars(
                select(WorkoutPlanExercise)
                .where(WorkoutPlanExercise.workout_plan_id == plan_id)
                .order_by(WorkoutPlanExercise.exercise_order)
            )
        ]


def test_a_saved_plan_survives_the_downgrade_and_the_upgrade_again(
    alembic_config, test_engine, service_session, activities
):
    plan_id = plan_with(
        service_session, "saved-plan-roundtrip@example.com", ["Cat-Cow", "Arm Circles"]
    )
    service_session.close()
    before = plan_rows(test_engine, plan_id)

    command.downgrade(alembic_config, PROPOSALS_REVISION)
    assert plan_rows(test_engine, plan_id) == before
    with Session(test_engine) as session:
        cat_cow = formiqs_exercises(session)["Cat-Cow"]
    assert cat_cow["description"] == activities.OLD_DESCRIPTIONS["Cat-Cow"]

    command.upgrade(alembic_config, "head")
    assert plan_rows(test_engine, plan_id) == before
    with Session(test_engine) as session:
        cat_cow = formiqs_exercises(session)["Cat-Cow"]
    assert cat_cow["description"] == new_text(activities, "Cat-Cow")


def test_a_plan_that_uses_a_new_activity_stops_the_downgrade_and_nothing_changes(
    alembic_config, test_engine, service_session, activities
):
    plan_id = plan_with(
        service_session, "saved-plan-blocks@example.com", ["Cat-Cow", "Wall Push-Up", "Easy Walk"]
    )
    service_session.close()
    before = plan_rows(test_engine, plan_id)
    with Session(test_engine) as session:
        catalog_before = formiqs_exercises(session)

    with pytest.raises(IntegrityError):
        command.downgrade(alembic_config, PROPOSALS_REVISION)

    # one transaction: the descriptions it had restored first are as they were, and no
    # activity the plan does not use was deleted
    # the whole downgrade is one transaction: still at head, which the treadmill migration is now
    assert current_revision(test_engine) == TREADMILL_REVISION
    assert plan_rows(test_engine, plan_id) == before
    with Session(test_engine) as session:
        assert formiqs_exercises(session) == catalog_before
