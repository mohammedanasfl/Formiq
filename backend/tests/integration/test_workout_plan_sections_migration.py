"""Integration tests for the workout plan sections migration and the later
catalog seed (warm-up and cool-down activities).

They require the local PostgreSQL container to be running. They upgrade and
downgrade the test database (TEST_DATABASE_URL), and leave it at head. The
schema/model consistency check (alembic check) is test_models_match_migrations
in test_users_migration.py.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, table, text, update
from sqlalchemy.orm import Session

from app.models import Exercise, ExerciseMuscle, User, WorkoutPlan, WorkoutPlanExercise
from app.models.exercise_equipment import exercise_equipment

CREDENTIALS_REVISION = "c3a1f2d9e8b7"
SECTIONS_REVISION = "c062e4afd0b0"
LATER_SEED_REVISION = "14d543e636a8"


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


def catalog_counts(engine):
    with Session(engine) as session:
        return [
            session.scalar(select(func.count()).select_from(source))
            for source in (Exercise, ExerciseMuscle, exercise_equipment, table("equipment"))
        ]


def test_the_sections_migration_and_the_later_seed_follow_the_credentials(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(SECTIONS_REVISION).down_revision == CREDENTIALS_REVISION
    assert script.get_revision(LATER_SEED_REVISION).down_revision == SECTIONS_REVISION
    assert LATER_SEED_REVISION in {
        revision.revision
        for revision in script.iterate_revisions(script.get_current_head(), "base")
    }


def test_existing_plan_exercises_become_main_workout_and_keep_their_reps(
    alembic_config, test_engine, service_session, catalog_exercise_ids
):
    command.downgrade(alembic_config, CREDENTIALS_REVISION)
    # a plan made before sections existed, written as that schema has it
    user = User(email="sections-migration@example.com")
    service_session.add(user)
    service_session.flush()
    plan = WorkoutPlan(user_id=user.id, name="Old Plan", status="DRAFT")
    service_session.add(plan)
    service_session.flush()
    service_session.execute(
        text(
            "INSERT INTO workout_plan_exercises "
            "(workout_plan_id, exercise_id, exercise_order, sets, reps, rest_seconds) "
            "VALUES (:plan, :exercise, 1, 4, 6, 120)"
        ),
        {"plan": plan.id, "exercise": catalog_exercise_ids["Barbell Back Squat"]},
    )
    service_session.commit()
    plan_id = plan.id

    command.upgrade(alembic_config, "head")

    with Session(test_engine) as session:
        (item,) = session.get(WorkoutPlan, plan_id).exercises
        # MAIN at the sections revision, named MAIN_WORKOUT since (cf98650b3833)
        assert (item.section, item.sets, item.reps, item.duration_seconds, item.rest_seconds) == (
            "MAIN_WORKOUT",
            4,
            6,
            None,
            120,
        )


def test_the_downgrade_refuses_plans_the_earlier_schema_cannot_hold(
    alembic_config, test_engine, service_session, catalog_exercise_ids
):
    user = User(email="sections-downgrade@example.com")
    service_session.add(user)
    service_session.flush()
    # a first-seed exercise, so only the sections downgrade can refuse it
    plan = WorkoutPlan(
        user_id=user.id,
        name="Warm Plan",
        status="DRAFT",
        exercises=[
            WorkoutPlanExercise(
                exercise_id=catalog_exercise_ids["Push-Up"],
                exercise_order=1,
                section="WARM_UP",
                sets=1,
                reps=5,
            )
        ],
    )
    service_session.add(plan)
    service_session.commit()
    counts = catalog_counts(test_engine)

    with pytest.raises(RuntimeError, match="warm-up, cool-down or timed exercises"):
        command.downgrade(alembic_config, CREDENTIALS_REVISION)

    # the whole downgrade is one transaction: nothing changed, the seed included
    with Session(test_engine) as session:
        (item,) = session.get(WorkoutPlan, plan.id).exercises
        assert item.section == "WARM_UP"
    assert catalog_counts(test_engine) == counts


def test_running_the_later_seed_again_adds_nothing_and_changes_nothing(
    alembic_config, test_engine
):
    before = catalog_counts(test_engine)
    with Session(test_engine) as session:
        walk = session.scalars(select(Exercise).where(Exercise.name == "Brisk Walk")).one()
        original = walk.description
        walk.description = "Changed after seeding"
        session.commit()

    try:
        # mark the seed as not applied while its rows are still there and run it
        # again; then mark the database as being at head again, which it is
        command.stamp(alembic_config, SECTIONS_REVISION)
        try:
            command.upgrade(alembic_config, LATER_SEED_REVISION)
        finally:
            command.stamp(alembic_config, "head")

        assert catalog_counts(test_engine) == before
        with Session(test_engine) as session:
            # an existing row is left as it is
            assert session.scalar(
                select(Exercise.description).where(Exercise.name == "Brisk Walk")
            ) == "Changed after seeding"
    finally:
        with Session(test_engine) as session:
            session.execute(
                update(Exercise).where(Exercise.name == "Brisk Walk").values(description=original)
            )
            session.commit()


def test_the_later_seed_downgrade_removes_only_its_own_rows(alembic_config, test_engine):
    before = catalog_counts(test_engine)
    first_seed = ScriptDirectory.from_config(alembic_config).get_revision("b84c61ea69bf").module

    command.downgrade(alembic_config, SECTIONS_REVISION)
    with Session(test_engine) as session:
        assert set(session.scalars(select(Exercise.name))) == {
            exercise["name"] for exercise in first_seed.EXERCISES
        }

    command.upgrade(alembic_config, "head")
    assert catalog_counts(test_engine) == before
