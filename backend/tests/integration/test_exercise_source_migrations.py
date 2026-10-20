"""Integration tests for the migrations that prepare the catalog for imported
exercises and keep proposals in the database: cf98650b3833 (the main plan
section is MAIN_WORKOUT), 620eafb9c204 (exercise source, uses and images) and
9f7cfca45752 (workout_plan_proposals).

They upgrade and downgrade the test database (TEST_DATABASE_URL), leave it at
head, and require the local PostgreSQL container to be running. The
schema/model consistency check is test_models_match_migrations in
test_users_migration.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from app.models import Exercise, User, WorkoutPlan, WorkoutPlanExercise

LATER_SEED_REVISION = "14d543e636a8"
SECTION_NAME_REVISION = "cf98650b3833"
SOURCE_REVISION = "620eafb9c204"
PROPOSALS_REVISION = "9f7cfca45752"


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


def test_the_migrations_follow_the_later_seed_in_order(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_revision(SECTION_NAME_REVISION).down_revision == LATER_SEED_REVISION
    assert script.get_revision(SOURCE_REVISION).down_revision == SECTION_NAME_REVISION
    assert script.get_revision(PROPOSALS_REVISION).down_revision == SOURCE_REVISION


def test_main_plan_exercises_become_main_workout_and_back(
    alembic_config, test_engine, service_session, catalog_exercise_ids
):
    command.downgrade(alembic_config, LATER_SEED_REVISION)
    user = User(email="section-name@example.com")
    service_session.add(user)
    service_session.flush()
    plan = WorkoutPlan(user_id=user.id, name="Named", status="DRAFT")
    service_session.add(plan)
    service_session.flush()
    for order, section in ((1, "WARM_UP"), (2, "MAIN"), (3, "COOL_DOWN")):
        service_session.execute(
            text(
                "INSERT INTO workout_plan_exercises "
                "(workout_plan_id, exercise_id, exercise_order, section, sets, reps) "
                "VALUES (:plan, :exercise, :order, :section, 2, 10)"
            ),
            {
                "plan": plan.id,
                "exercise": catalog_exercise_ids["Push-Up"],
                "order": order,
                "section": section,
            },
        )
    # and one written without a section, as before sections existed
    service_session.execute(
        text(
            "INSERT INTO workout_plan_exercises "
            "(workout_plan_id, exercise_id, exercise_order, sets, reps) "
            "VALUES (:plan, :exercise, 4, 3, 8)"
        ),
        {"plan": plan.id, "exercise": catalog_exercise_ids["Push-Up"]},
    )
    plan_id = plan.id
    service_session.commit()
    # no transaction left open to hold a lock the migrations need
    service_session.close()

    def sections():
        with Session(test_engine) as session:
            return session.scalars(
                select(WorkoutPlanExercise.section)
                .where(WorkoutPlanExercise.workout_plan_id == plan_id)
                .order_by(WorkoutPlanExercise.exercise_order)
            ).all()

    assert sections() == ["WARM_UP", "MAIN", "COOL_DOWN", "MAIN"]

    command.upgrade(alembic_config, "head")
    assert sections() == ["WARM_UP", "MAIN_WORKOUT", "COOL_DOWN", "MAIN_WORKOUT"]
    defaults = {
        column["name"]: column["default"]
        for column in inspect(test_engine).get_columns("workout_plan_exercises")
    }
    assert defaults["section"] == "'MAIN_WORKOUT'::character varying"

    command.downgrade(alembic_config, LATER_SEED_REVISION)
    assert sections() == ["WARM_UP", "MAIN", "COOL_DOWN", "MAIN"]


def test_formiqs_own_exercises_are_classified_and_marked_as_formiqs(alembic_config, db_session):
    exercises = db_session.scalars(select(Exercise)).all()

    # the 50 of the first two seeds, and the 21 activities a7d3f1c82e4b adds
    assert len(exercises) == 50 + 21
    assert {(e.source, e.source_id, e.source_version, e.source_record) for e in exercises} == {
        ("FORMIQ", None, None, None)
    }
    assert all(e.image_paths == [] for e in exercises)
    uses = {e.name: e.uses for e in exercises}
    # by movement pattern: strength trains, mobility warms up, stretches cool down,
    # easy cardio does both
    assert uses["Barbell Bench Press"] == ["MAIN_WORKOUT"]
    assert uses["Arm Circles"] == ["WARM_UP"]
    assert uses["Standing Quad Stretch"] == ["COOL_DOWN"]
    assert uses["Brisk Walk"] == ["WARM_UP", "COOL_DOWN"]
    # and the exceptions
    assert uses["Jumping Jacks"] == ["WARM_UP"]
    assert uses["Cat-Cow"] == ["WARM_UP", "COOL_DOWN"]
    assert uses["Bird Dog"] == ["WARM_UP", "MAIN_WORKOUT"]
    assert all(e.uses for e in exercises)


def test_the_source_downgrade_refuses_a_catalog_with_imported_exercises(
    alembic_config, test_engine
):
    with Session(test_engine) as session:
        session.add(
            Exercise(
                name="Test Imported Migration Exercise",
                difficulty="BEGINNER",
                movement_pattern=None,
                source="FREE_EXERCISE_DB",
                source_id="Test_Imported",
                source_record={"id": "Test_Imported"},
            )
        )
        session.commit()
    try:
        with pytest.raises(RuntimeError, match="imported or unclassified exercises"):
            command.downgrade(alembic_config, SECTION_NAME_REVISION)
        # nothing changed: the downgrade is one transaction
        with Session(test_engine) as session:
            imported = session.scalars(
                select(Exercise).where(Exercise.source_id == "Test_Imported")
            ).one()
            assert imported.source_record == {"id": "Test_Imported"}
    finally:
        with Session(test_engine) as session:
            session.execute(
                Exercise.__table__.delete().where(Exercise.source_id == "Test_Imported")
            )
            session.commit()


def test_the_source_migration_downgrades_and_upgrades_again(alembic_config, test_engine):
    def catalog():
        with Session(test_engine) as session:
            return (
                sorted(session.scalars(text("SELECT name FROM muscle_groups"))),
                sorted(session.scalars(text("SELECT name FROM equipment"))),
            )

    before = catalog()

    command.downgrade(alembic_config, SECTION_NAME_REVISION)
    columns = {column["name"] for column in inspect(test_engine).get_columns("exercises")}
    assert not columns & {"uses", "image_paths", "source", "source_id", "source_record"}
    assert "Foam Roller" not in catalog()[1]
    assert "Neck" not in catalog()[0]

    command.upgrade(alembic_config, "head")
    assert catalog() == before


def test_proposals_are_kept_in_their_own_table(alembic_config, test_engine, service_session):
    inspector = inspect(test_engine)
    columns = {
        column["name"]: column["nullable"]
        for column in inspector.get_columns("workout_plan_proposals")
    }

    assert columns == {
        "proposal_id": False,
        "user_id": False,
        "action": False,
        "parameters": False,
        "binding": False,
        "status": False,
        "created_at": False,
        "expires_at": False,
        "approved_at": True,
        "workout_plan_id": True,
        "recorded_at": False,
    }
    assert inspector.get_pk_constraint("workout_plan_proposals")["constrained_columns"] == [
        "proposal_id"
    ]
    assert {
        (key["constrained_columns"][0], key["referred_table"], key["options"]["ondelete"])
        for key in inspector.get_foreign_keys("workout_plan_proposals")
    } == {("user_id", "users", "CASCADE"), ("workout_plan_id", "workout_plans", "SET NULL")}

    # a user's proposals go with the user
    user = User(email="proposal-table@example.com")
    service_session.add(user)
    service_session.flush()
    now = datetime(2026, 10, 13, tzinfo=UTC)
    service_session.execute(
        text(
            "INSERT INTO workout_plan_proposals (proposal_id, user_id, action, parameters, "
            "binding, status, created_at, expires_at) VALUES (:id, :user, 'create_workout_plan', "
            "'{}', :binding, 'PENDING', :now, :expires)"
        ),
        {
            "id": "a" * 32,
            "user": user.id,
            "binding": "b" * 64,
            "now": now,
            "expires": now + timedelta(minutes=30),
        },
    )
    service_session.commit()
    service_session.delete(service_session.get(User, user.id))
    service_session.commit()
    assert service_session.scalar(text("SELECT count(*) FROM workout_plan_proposals")) == 0


def test_the_proposals_downgrade_drops_the_table(alembic_config, test_engine):
    command.downgrade(alembic_config, SOURCE_REVISION)
    assert "workout_plan_proposals" not in inspect(test_engine).get_table_names()

    command.upgrade(alembic_config, "head")
    assert "workout_plan_proposals" in inspect(test_engine).get_table_names()
