"""Integration tests for the users and user_profiles migration.

They require the local PostgreSQL container to be running. They upgrade and
downgrade the database that DATABASE_URL points to, and leave it at head.
Rows are only added inside transactions that are rolled back.
"""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from psycopg.errors import UniqueViolation
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.db.database import engine
from app.models import User, UserProfile

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"

# The revision before the users and user_profiles migration.
REVISION_BEFORE_USERS = "a4020d4605a0"

USERS_COLUMNS = {"id", "email", "phone", "created_at", "updated_at"}

USERS_NULLABLE_COLUMNS = {"email", "phone"}

USER_PROFILES_COLUMNS = {
    "id",
    "user_id",
    "first_name",
    "last_name",
    "age",
    "height_cm",
    "weight_kg",
    "gender",
    "fitness_experience",
    "goal",
    "target_weight_kg",
    "goal_period_weeks",
    "training_frequency_per_week",
    "training_location",
    "activity_level",
    "sleep_hours",
    "dietary_preference",
    "created_at",
    "updated_at",
}

USER_PROFILES_NULLABLE_COLUMNS = {
    "last_name",
    "target_weight_kg",
    "goal_period_weeks",
    "dietary_preference",
}

# Values for the required profile fields.
PROFILE_FIELDS = {
    "first_name": "Test",
    "age": 30,
    "height_cm": 175.0,
    "weight_kg": 70.0,
    "gender": "other",
    "fitness_experience": "beginner",
    "goal": "general_fitness",
    "training_frequency_per_week": 3,
    "training_location": "gym",
    "activity_level": "moderate",
    "sleep_hours": 7.5,
}


@pytest.fixture
def alembic_config():
    config = Config(str(ALEMBIC_INI))
    command.upgrade(config, "head")
    yield config
    command.upgrade(config, "head")


def table_names():
    return inspect(engine).get_table_names()


def test_upgrade_creates_users_and_user_profiles_tables(alembic_config):
    assert {"users", "user_profiles"} <= set(table_names())


def test_users_table_has_expected_columns(alembic_config):
    inspector = inspect(engine)
    columns = inspector.get_columns("users")
    unique_constraints = inspector.get_unique_constraints("users")

    assert {column["name"] for column in columns} == USERS_COLUMNS
    assert {column["name"] for column in columns if column["nullable"]} == USERS_NULLABLE_COLUMNS
    assert inspector.get_pk_constraint("users")["constrained_columns"] == ["id"]
    assert {tuple(c["column_names"]) for c in unique_constraints} == {("email",), ("phone",)}


def test_user_profiles_table_has_expected_columns(alembic_config):
    inspector = inspect(engine)
    columns = inspector.get_columns("user_profiles")

    assert {column["name"] for column in columns} == USER_PROFILES_COLUMNS
    assert {
        column["name"] for column in columns if column["nullable"]
    } == USER_PROFILES_NULLABLE_COLUMNS
    assert inspector.get_pk_constraint("user_profiles")["constrained_columns"] == ["id"]


def test_user_profiles_user_id_references_users_id(alembic_config):
    foreign_keys = inspect(engine).get_foreign_keys("user_profiles")

    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["user_id"]
    assert foreign_keys[0]["referred_table"] == "users"
    assert foreign_keys[0]["referred_columns"] == ["id"]


def test_user_profiles_user_id_is_unique(alembic_config):
    unique_constraints = inspect(engine).get_unique_constraints("user_profiles")

    assert ["user_id"] in [c["column_names"] for c in unique_constraints]


def test_user_can_have_one_profile(alembic_config, db_session):
    user = User()
    profile = UserProfile(user=user, **PROFILE_FIELDS)
    db_session.add(user)
    db_session.flush()
    db_session.expire_all()  # load the relationship from the database

    assert profile.user_id == user.id
    assert user.profile is profile
    assert profile.user is user


def test_user_cannot_have_two_profiles(alembic_config, db_session):
    user = User()
    db_session.add(UserProfile(user=user, **PROFILE_FIELDS))
    db_session.flush()

    db_session.add(UserProfile(user_id=user.id, **PROFILE_FIELDS))
    with pytest.raises(IntegrityError) as error:
        db_session.flush()

    assert isinstance(error.value.orig, UniqueViolation)


def test_downgrade_removes_tables_and_upgrade_recreates_them(alembic_config):
    command.downgrade(alembic_config, REVISION_BEFORE_USERS)
    assert not {"users", "user_profiles"} & set(table_names())

    command.upgrade(alembic_config, "head")
    assert {"users", "user_profiles"} <= set(table_names())


def test_models_match_migrations(alembic_config):
    command.check(alembic_config)
