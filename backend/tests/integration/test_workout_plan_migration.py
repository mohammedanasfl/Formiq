"""Integration tests for the workout plan migration.

They require the local PostgreSQL container to be running. They upgrade and
downgrade the test database (TEST_DATABASE_URL), and leave it at head. The
schema/model consistency check (alembic check) is test_models_match_migrations
in test_users_migration.py.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import func, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import Exercise, User, UserProfile

# The Phase 3.1 head: the exercise catalog and its seed data.
REVISION_BEFORE_WORKOUT_PLANS = "b84c61ea69bf"
WORKOUT_PLANS_REVISION = "7625680f92a6"

TIMESTAMPTZ = "TIMESTAMP WITH TIME ZONE"

# For each table: column types, nullable columns and primary key.
WORKOUT_PLAN_TABLES = {
    "workout_plans": (
        {
            "id": "INTEGER",
            "user_id": "INTEGER",
            "name": "VARCHAR(150)",
            "description": "TEXT",
            "status": "VARCHAR(20)",
            "scheduled_date": "DATE",
            "created_at": TIMESTAMPTZ,
            "updated_at": TIMESTAMPTZ,
        },
        {"description", "scheduled_date"},
        ["id"],
    ),
    "workout_plan_exercises": (
        {
            "id": "INTEGER",
            "workout_plan_id": "INTEGER",
            "exercise_id": "INTEGER",
            "exercise_order": "INTEGER",
            "sets": "INTEGER",
            "reps": "INTEGER",
            "weight_kg": "DOUBLE PRECISION",
            "rest_seconds": "INTEGER",
            "notes": "TEXT",
            "created_at": TIMESTAMPTZ,
            "updated_at": TIMESTAMPTZ,
        },
        {"weight_kg", "rest_seconds", "notes"},
        ["id"],
    ),
}

# (table, column, referred table, ON DELETE rule)
FOREIGN_KEYS = {
    ("workout_plans", "user_id", "users", "RESTRICT"),
    ("workout_plan_exercises", "workout_plan_id", "workout_plans", "CASCADE"),
    ("workout_plan_exercises", "exercise_id", "exercises", "RESTRICT"),
}


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


def table_names(engine):
    return set(inspect(engine).get_table_names())


def test_workout_plan_migration_follows_the_exercise_catalog(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)
    head = script.get_current_head()

    assert (
        script.get_revision(WORKOUT_PLANS_REVISION).down_revision == REVISION_BEFORE_WORKOUT_PLANS
    )
    assert WORKOUT_PLANS_REVISION in {
        revision.revision for revision in script.iterate_revisions(head, "base")
    }


@pytest.mark.parametrize("table_name", WORKOUT_PLAN_TABLES)
def test_workout_plan_table_has_expected_columns(alembic_config, test_engine, table_name):
    column_types, nullable, primary_key = WORKOUT_PLAN_TABLES[table_name]
    inspector = inspect(test_engine)
    columns = inspector.get_columns(table_name)

    assert {
        column["name"]: column["type"].compile(dialect=postgresql.dialect()) for column in columns
    } == column_types
    assert {column["name"] for column in columns if column["nullable"]} == nullable
    assert inspector.get_pk_constraint(table_name)["constrained_columns"] == primary_key


def test_foreign_keys_have_deliberate_delete_rules(alembic_config, test_engine):
    inspector = inspect(test_engine)
    foreign_keys = {
        (table_name, *key["constrained_columns"], key["referred_table"], key["options"]["ondelete"])
        for table_name in WORKOUT_PLAN_TABLES
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_columns"] == ["id"]
    }

    assert foreign_keys == FOREIGN_KEYS


def test_only_the_exercise_order_is_unique_within_a_plan(alembic_config, test_engine):
    inspector = inspect(test_engine)

    # not the exercise in a plan, and not a user's scheduled date
    assert [
        c["column_names"] for c in inspector.get_unique_constraints("workout_plan_exercises")
    ] == [["workout_plan_id", "exercise_order"]]
    assert inspector.get_unique_constraints("workout_plans") == []


@pytest.mark.parametrize(
    ("table_name", "column"),
    [("workout_plans", "user_id"), ("workout_plan_exercises", "exercise_id")],
)
def test_foreign_key_columns_are_indexed(alembic_config, test_engine, table_name, column):
    # workout_plan_id is covered by the unique constraint's index, which starts with it
    indexes = [
        index
        for index in inspect(test_engine).get_indexes(table_name)
        if "duplicates_constraint" not in index  # the unique constraint's own index
    ]

    assert [(index["column_names"], index["unique"]) for index in indexes] == [([column], False)]


def test_downgrade_keeps_users_and_the_catalog_and_upgrade_recreates_the_tables(
    alembic_config, test_engine, service_session, profile_fields
):
    user = User(email="plan-migration@example.com")
    service_session.add(UserProfile(user=user, **profile_fields))
    service_session.flush()
    user_id = user.id
    service_session.commit()
    with Session(test_engine) as session:
        exercises = session.scalar(select(func.count()).select_from(Exercise))

    command.downgrade(alembic_config, REVISION_BEFORE_WORKOUT_PLANS)
    assert not set(WORKOUT_PLAN_TABLES) & table_names(test_engine)
    with Session(test_engine) as session:
        assert session.get(User, user_id).profile.first_name == profile_fields["first_name"]
        assert session.scalar(select(func.count()).select_from(Exercise)) == exercises

    command.upgrade(alembic_config, "head")
    assert set(WORKOUT_PLAN_TABLES) <= table_names(test_engine)
    with Session(test_engine) as session:
        assert session.get(User, user_id).profile.first_name == profile_fields["first_name"]
