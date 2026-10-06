"""Integration tests proving the tests use the dedicated test database.

The check_test_database_url tests need no database. The others require the
local PostgreSQL container to be running.
"""

import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User
from tests.integration.database import TEST_DATABASE_NAME, check_test_database_url

TEST_URL = "postgresql+psycopg://formiq:formiq@localhost:5432/formiq_test"
DEV_URL = "postgresql+psycopg://formiq:formiq@localhost:5432/formiq"


@pytest.mark.parametrize("test_database_url", [None, ""])
def test_check_rejects_missing_test_database_url(test_database_url):
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL is not set"):
        check_test_database_url(test_database_url, DEV_URL)


@pytest.mark.parametrize(
    "test_database_url",
    [
        DEV_URL,
        # the same database, written differently
        "postgresql+psycopg://formiq:formiq@127.0.0.1:5432/formiq",
    ],
)
def test_check_rejects_the_development_database(test_database_url):
    with pytest.raises(RuntimeError, match="same database as DATABASE_URL"):
        check_test_database_url(test_database_url, DEV_URL)


def test_check_rejects_the_configured_database_url():
    with pytest.raises(RuntimeError, match="same database as DATABASE_URL"):
        check_test_database_url(settings.database_url, settings.database_url)


def test_check_rejects_a_database_other_than_formiq_test():
    with pytest.raises(RuntimeError, match="must point to the 'formiq_test' database"):
        check_test_database_url(
            "postgresql+psycopg://formiq:formiq@localhost:5432/postgres", DEV_URL
        )


def test_check_accepts_the_test_database():
    assert check_test_database_url(TEST_URL, DEV_URL) == TEST_URL


def test_configured_test_database_url_is_separate_from_database_url(test_database_url):
    assert test_database_url == settings.test_database_url
    assert make_url(test_database_url).database == TEST_DATABASE_NAME
    assert make_url(settings.database_url).database != TEST_DATABASE_NAME


def test_test_engine_uses_test_database_url(test_engine, test_database_url):
    assert test_engine.url.render_as_string(hide_password=False) == test_database_url
    assert test_engine.url.database == TEST_DATABASE_NAME


def test_db_session_is_connected_to_the_test_database(db_session):
    assert db_session.execute(text("SELECT current_database()")).scalar_one() == TEST_DATABASE_NAME


def test_test_database_is_migrated_to_head(test_engine, test_alembic_config):
    head = ScriptDirectory.from_config(test_alembic_config).get_current_head()

    with test_engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()

    assert current == head


def test_closed_session_leaves_no_rows_behind(test_engine):
    email = "isolation-cleanup@example.com"
    with Session(test_engine) as session:
        session.add(User(email=email))
        session.flush()
    # closing the session without commit rolls the insert back

    with Session(test_engine) as session:
        count = session.scalar(select(func.count()).select_from(User).where(User.email == email))

    assert count == 0
