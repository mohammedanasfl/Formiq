"""Integration tests for the workout session migration.

They require the local PostgreSQL container to be running. They upgrade and
downgrade the test database (TEST_DATABASE_URL), and leave it at head. The
schema/model consistency check (alembic check) is test_models_match_migrations
in test_users_migration.py.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.models import User, WorkoutPlan
from tests.integration.workout_plans import add_plan

# The Phase 3.2 head: workout plans.
REVISION_BEFORE_WORKOUT_SESSIONS = "7625680f92a6"
WORKOUT_SESSIONS_REVISION = "5559eac720c2"

TIMESTAMPTZ = "TIMESTAMP WITH TIME ZONE"

# For each table: column types, nullable columns and primary key.
WORKOUT_SESSION_TABLES = {
    "workout_sessions": (
        {
            "id": "INTEGER",
            "user_id": "INTEGER",
            "workout_plan_id": "INTEGER",
            "started_at": TIMESTAMPTZ,
            "completed_at": TIMESTAMPTZ,
            "status": "VARCHAR(20)",
            "notes": "TEXT",
            "created_at": TIMESTAMPTZ,
            "updated_at": TIMESTAMPTZ,
        },
        {"workout_plan_id", "completed_at", "notes"},
        ["id"],
    ),
    "workout_session_exercises": (
        {
            "id": "INTEGER",
            "workout_session_id": "INTEGER",
            "plan_exercise_id": "INTEGER",
            "exercise_id": "INTEGER",
            "exercise_order": "INTEGER",
            "notes": "TEXT",
            "created_at": TIMESTAMPTZ,
            "updated_at": TIMESTAMPTZ,
        },
        {"plan_exercise_id", "notes"},
        ["id"],
    ),
    "workout_sets": (
        {
            "id": "INTEGER",
            "workout_session_exercise_id": "INTEGER",
            "set_number": "INTEGER",
            "reps": "INTEGER",
            "weight_kg": "DOUBLE PRECISION",
            "rpe": "DOUBLE PRECISION",
            "completed": "BOOLEAN",
            "notes": "TEXT",
            "created_at": TIMESTAMPTZ,
            "updated_at": TIMESTAMPTZ,
        },
        {"weight_kg", "rpe", "notes"},
        ["id"],
    ),
}

# (table, column, referred table, ON DELETE rule)
FOREIGN_KEYS = {
    ("workout_sessions", "user_id", "users", "RESTRICT"),
    ("workout_sessions", "workout_plan_id", "workout_plans", "SET NULL"),
    ("workout_session_exercises", "workout_session_id", "workout_sessions", "CASCADE"),
    ("workout_session_exercises", "plan_exercise_id", "workout_plan_exercises", "SET NULL"),
    ("workout_session_exercises", "exercise_id", "exercises", "RESTRICT"),
    ("workout_sets", "workout_session_exercise_id", "workout_session_exercises", "CASCADE"),
}


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


def table_names(engine):
    return set(inspect(engine).get_table_names())


def test_workout_session_migration_follows_the_workout_plans(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)
    head = script.get_current_head()

    assert (
        script.get_revision(WORKOUT_SESSIONS_REVISION).down_revision
        == REVISION_BEFORE_WORKOUT_SESSIONS
    )
    assert WORKOUT_SESSIONS_REVISION in {
        revision.revision for revision in script.iterate_revisions(head, "base")
    }


@pytest.mark.parametrize("table_name", WORKOUT_SESSION_TABLES)
def test_workout_session_table_has_expected_columns(alembic_config, test_engine, table_name):
    column_types, nullable, primary_key = WORKOUT_SESSION_TABLES[table_name]
    inspector = inspect(test_engine)
    columns = inspector.get_columns(table_name)

    assert {
        column["name"]: column["type"].compile(dialect=postgresql.dialect()) for column in columns
    } == column_types
    assert {column["name"] for column in columns if column["nullable"]} == nullable
    assert inspector.get_pk_constraint(table_name)["constrained_columns"] == primary_key


def test_server_defaults(alembic_config, test_engine):
    inspector = inspect(test_engine)
    sessions = {c["name"]: c["default"] for c in inspector.get_columns("workout_sessions")}
    sets = {c["name"]: c["default"] for c in inspector.get_columns("workout_sets")}

    # started_at is set by the database; completed_at only by the service
    assert sessions["started_at"] == "now()"
    assert sessions["completed_at"] is None
    assert sets["completed"] == "true"


def test_foreign_keys_have_deliberate_delete_rules(alembic_config, test_engine):
    inspector = inspect(test_engine)
    foreign_keys = {
        (table_name, *key["constrained_columns"], key["referred_table"], key["options"]["ondelete"])
        for table_name in WORKOUT_SESSION_TABLES
        for key in inspector.get_foreign_keys(table_name)
        if key["referred_columns"] == ["id"]
    }

    assert foreign_keys == FOREIGN_KEYS


@pytest.mark.parametrize(
    ("table_name", "unique_columns"),
    [
        ("workout_sessions", []),
        ("workout_session_exercises", [["workout_session_id", "exercise_order"]]),
        ("workout_sets", [["workout_session_exercise_id", "set_number"]]),
    ],
)
def test_only_positions_are_unique(alembic_config, test_engine, table_name, unique_columns):
    # not the exercise within a session, and not a user's sessions of a day
    unique_constraints = inspect(test_engine).get_unique_constraints(table_name)

    assert [c["column_names"] for c in unique_constraints] == unique_columns


@pytest.mark.parametrize(
    ("table_name", "columns"),
    [
        ("workout_sessions", [["user_id"], ["workout_plan_id"]]),
        ("workout_session_exercises", [["exercise_id"], ["plan_exercise_id"]]),
        ("workout_sets", []),
    ],
)
def test_foreign_key_columns_are_indexed(alembic_config, test_engine, table_name, columns):
    # the parent key of exercises and sets is covered by the unique constraint's
    # index, which starts with it
    indexes = [
        index
        for index in inspect(test_engine).get_indexes(table_name)
        if "duplicates_constraint" not in index  # the unique constraint's own index
    ]

    assert sorted(index["column_names"] for index in indexes) == sorted(columns)
    assert not any(index["unique"] for index in indexes)


def test_downgrade_keeps_users_and_plans_and_upgrade_recreates_the_tables(
    alembic_config, test_engine, service_session, catalog_exercise_ids
):
    user = User(email="session-migration@example.com")
    service_session.add(user)
    service_session.flush()
    user_id = user.id
    plan_id = add_plan(
        service_session, user, exercise_ids=[catalog_exercise_ids["Barbell Bench Press"]]
    ).id
    service_session.commit()

    command.downgrade(alembic_config, REVISION_BEFORE_WORKOUT_SESSIONS)
    assert not set(WORKOUT_SESSION_TABLES) & table_names(test_engine)
    with Session(test_engine) as session:
        assert session.get(User, user_id) is not None
        assert len(session.get(WorkoutPlan, plan_id).exercises) == 1

    command.upgrade(alembic_config, "head")
    assert set(WORKOUT_SESSION_TABLES) <= table_names(test_engine)
    with Session(test_engine) as session:
        assert session.get(User, user_id) is not None
        assert len(session.get(WorkoutPlan, plan_id).exercises) == 1
