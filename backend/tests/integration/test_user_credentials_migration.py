"""Integration tests for the user_credentials migration.

They require the local PostgreSQL container to be running. They upgrade and
downgrade the test database (TEST_DATABASE_URL), and leave it at head. The
users they commit are deleted afterwards by service_session.
"""

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import User, UserCredential

REVISION_BEFORE_CREDENTIALS = "5559eac720c2"
CREDENTIALS_REVISION = "c3a1f2d9e8b7"
COLUMNS = {
    "user_id": "INTEGER",
    "password_hash": "VARCHAR(255)",
    "created_at": "TIMESTAMP WITH TIME ZONE",
    "updated_at": "TIMESTAMP WITH TIME ZONE",
}


@pytest.fixture
def alembic_config(test_alembic_config):
    command.upgrade(test_alembic_config, "head")
    yield test_alembic_config
    command.upgrade(test_alembic_config, "head")


def test_the_credentials_migration_is_the_head_after_the_workout_sessions(alembic_config):
    script = ScriptDirectory.from_config(alembic_config)

    assert script.get_current_head() == CREDENTIALS_REVISION
    assert script.get_revision(CREDENTIALS_REVISION).down_revision == REVISION_BEFORE_CREDENTIALS


def test_the_table_holds_one_hash_per_user(alembic_config, test_engine):
    inspector = inspect(test_engine)
    columns = inspector.get_columns("user_credentials")
    (foreign_key,) = inspector.get_foreign_keys("user_credentials")

    assert {
        column["name"]: column["type"].compile(dialect=postgresql.dialect()) for column in columns
    } == COLUMNS
    assert not any(column["nullable"] for column in columns)
    assert inspector.get_pk_constraint("user_credentials")["constrained_columns"] == ["user_id"]
    assert (foreign_key["referred_table"], foreign_key["referred_columns"]) == ("users", ["id"])
    assert foreign_key["options"]["ondelete"] == "CASCADE"
    # nothing about a credential is added to the users table
    assert {column["name"] for column in inspector.get_columns("users")} == {
        "id",
        "email",
        "phone",
        "created_at",
        "updated_at",
    }


def test_a_credential_needs_a_user_and_goes_with_it(alembic_config, service_session):
    service_session.add(UserCredential(user_id=2_147_483_647, password_hash="$argon2id$x"))
    with pytest.raises(IntegrityError):
        service_session.flush()
    service_session.rollback()

    user = User(email="credential-cascade@example.com")
    service_session.add(user)
    service_session.flush()
    user_id = user.id
    service_session.add(UserCredential(user_id=user_id, password_hash="$argon2id$x"))
    service_session.commit()
    service_session.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
    service_session.commit()

    assert service_session.get(UserCredential, user_id) is None


def test_existing_users_are_kept_and_get_no_invented_password(
    alembic_config, test_engine, service_session
):
    command.downgrade(alembic_config, REVISION_BEFORE_CREDENTIALS)
    assert "user_credentials" not in inspect(test_engine).get_table_names()
    with Session(test_engine) as session:
        user_id = session.execute(
            text("INSERT INTO users (email) VALUES ('before-credentials@example.com') RETURNING id")
        ).scalar_one()
        session.commit()

    command.upgrade(alembic_config, "head")

    with Session(test_engine) as session:
        assert session.get(User, user_id) is not None
        assert session.get(UserCredential, user_id) is None


def test_downgrade_drops_only_the_credentials(alembic_config, test_engine, service_session):
    user = User(email="credential-downgrade@example.com")
    service_session.add(user)
    service_session.flush()
    user_id = user.id
    service_session.add(UserCredential(user_id=user_id, password_hash="$argon2id$x"))
    service_session.commit()
    # no open transaction may hold a lock the downgrade waits for
    service_session.close()

    command.downgrade(alembic_config, REVISION_BEFORE_CREDENTIALS)

    assert "user_credentials" not in inspect(test_engine).get_table_names()
    with Session(test_engine) as session:
        assert session.get(User, user_id) is not None
