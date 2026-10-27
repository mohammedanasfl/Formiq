"""Integration tests proving the tests use only the disposable test database.

Phase 2.7: the tests empty their database (every user, plan and session, before and after each
test) and migrate its schema down and up again, and a full run used to do that to `formiq_test`,
where QA accounts live. They now run in `formiq_pytest`, which they create and mark themselves
(tests.integration.database). The refusal tests need no database: they check what the guard does
with a URL or a connection it is given. The others require the local PostgreSQL container.
"""

import pytest
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import User
from tests.integration import database as guard
from tests.integration.conftest import delete_user_rows
from tests.integration.database import (
    DISPOSABLE_MARKER,
    TEST_DATABASE_NAME,
    assert_disposable,
    check_test_database_url,
    ensure_disposable_database,
)

SERVER = "postgresql+psycopg://formiq:formiq@localhost:5432"
DEV_URL = f"{SERVER}/formiq"


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


@pytest.mark.parametrize(
    "database", ["postgres", "template1", "formiq_prod", "formiq_qa", "formiq_pytest2", "FORMIQ_PYTEST"]
)
def test_check_rejects_every_database_but_the_approved_one(database):
    with pytest.raises(RuntimeError, match="must name the 'formiq_pytest' database"):
        check_test_database_url(f"{SERVER}/{database}", DEV_URL)


def test_check_accepts_the_approved_database_as_it_is():
    assert check_test_database_url(f"{SERVER}/formiq_pytest", DEV_URL) == f"{SERVER}/formiq_pytest"


def test_check_never_returns_the_qa_database_formiq_test():
    """TEST_DATABASE_URL still names `formiq_test` (what the setting held). That is only the
    address of the server: the URL the tests get is the disposable database, on that server,
    with the same login. The QA database is never returned."""
    url = check_test_database_url(f"{SERVER}/formiq_test", DEV_URL)

    assert make_url(url).database == TEST_DATABASE_NAME
    assert make_url(url).set(database="x") == make_url(f"{SERVER}/formiq_test").set(database="x")
    assert "formiq_test" not in url


@pytest.mark.parametrize("database", ["formiq", "formiq_test", "postgres", "template0", "template1"])
def test_the_connection_guard_refuses_every_protected_database(database):
    with pytest.raises(RuntimeError, match=f"refusing to change database '{database}'"):
        assert_disposable(StubConnection([[(database, DISPOSABLE_MARKER)]]))


@pytest.mark.parametrize("marker", [None, "", "formiq test database", DISPOSABLE_MARKER + " "])
def test_the_connection_guard_refuses_the_approved_name_without_the_marker(marker):
    """A database of the approved name that the tests did not make is not theirs to empty."""
    with pytest.raises(RuntimeError, match="not marked as disposable"):
        assert_disposable(StubConnection([[(TEST_DATABASE_NAME, marker)]]))


def test_the_connection_guard_accepts_the_marked_approved_database():
    assert_disposable(StubConnection([[(TEST_DATABASE_NAME, DISPOSABLE_MARKER)]]))


class StubResult:
    def __init__(self, rows):
        self.rows = rows

    def one(self):
        return self.rows[0]

    def all(self):
        return self.rows


class StubConnection:
    """A connection that answers its queries from a script and records every statement."""

    def __init__(self, answers, create_error=None):
        self.answers = list(answers)
        self.statements = []
        self.create_error = create_error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if sql.startswith("create database"):
            if self.create_error:
                raise self.create_error
            return StubResult([])
        return StubResult(self.answers.pop(0) if self.answers else [])

    def exec_driver_sql(self, sql):
        self.statements.append(sql)
        return StubResult([])


class StubEngine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def ensuring(monkeypatch, connection):
    engine = StubEngine(connection)
    monkeypatch.setattr(guard, "create_engine", lambda *args, **kwargs: engine)
    ensure_disposable_database(f"{SERVER}/{TEST_DATABASE_NAME}")
    return engine


def test_ensure_creates_and_marks_a_missing_database(monkeypatch):
    connection = StubConnection([[], [(DISPOSABLE_MARKER,)]])

    engine = ensuring(monkeypatch, connection)

    assert connection.statements[1] == f'create database "{TEST_DATABASE_NAME}"'
    assert f"comment on database \"{TEST_DATABASE_NAME}\" is '{DISPOSABLE_MARKER}'" in connection.statements
    assert engine.disposed


def test_ensure_leaves_an_existing_marked_database_as_it_is(monkeypatch):
    connection = StubConnection([[(DISPOSABLE_MARKER,)]])

    ensuring(monkeypatch, connection)

    assert not any(s.startswith(("create", "comment")) for s in connection.statements)


@pytest.mark.parametrize("marker", [None, "made by someone else"])
def test_ensure_refuses_an_existing_unmarked_database_and_never_marks_it(monkeypatch, marker):
    connection = StubConnection([[(marker,)]])

    with pytest.raises(RuntimeError, match="not marked as disposable"):
        ensuring(monkeypatch, connection)

    assert not any(s.startswith(("create", "comment")) for s in connection.statements)


def test_ensure_refuses_when_the_database_cannot_be_created(monkeypatch):
    error = ProgrammingError("create database", {}, Exception("permission denied to create database"))
    connection = StubConnection([[], []], create_error=error)

    with pytest.raises(RuntimeError, match="cannot create the 'formiq_pytest' database"):
        ensuring(monkeypatch, connection)


def test_ensure_never_creates_any_other_database():
    with pytest.raises(RuntimeError, match="refusing to create 'formiq_test'"):
        ensure_disposable_database(f"{SERVER}/formiq_test")


def test_configured_test_database_url_is_separate_from_database_url(test_database_url):
    assert make_url(test_database_url).database == TEST_DATABASE_NAME
    assert make_url(settings.database_url).database != TEST_DATABASE_NAME
    # not the QA database either, whatever TEST_DATABASE_URL names
    assert make_url(test_database_url).database != "formiq_test"


def test_the_migrations_are_run_on_the_disposable_database(test_alembic_config, test_database_url):
    assert test_alembic_config.attributes["database_url"] == test_database_url
    assert make_url(test_alembic_config.attributes["database_url"]).database == TEST_DATABASE_NAME


def test_test_engine_uses_the_disposable_database(test_engine, test_database_url):
    assert test_engine.url.render_as_string(hide_password=False) == test_database_url
    assert test_engine.url.database == TEST_DATABASE_NAME


def test_db_session_is_connected_to_the_test_database(db_session):
    assert db_session.execute(text("SELECT current_database()")).scalar_one() == TEST_DATABASE_NAME


def test_the_test_database_carries_the_tests_marker(db_session):
    assert_disposable(db_session.connection())


def test_test_database_is_migrated_to_head(test_engine, test_alembic_config):
    head = ScriptDirectory.from_config(test_alembic_config).get_current_head()

    with test_engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()

    assert current == head


def test_deleting_the_users_rows_asks_the_guard_first_and_stops_when_it_refuses(
    test_engine, monkeypatch
):
    """The deletion is the destructive step of every API and service test. If the guard refuses,
    nothing is deleted: a row committed beforehand is still there."""
    email = "isolation-guard@example.com"
    with Session(test_engine) as session:
        session.add(User(email=email))
        session.commit()
    checked = []

    def refusing(connection):
        checked.append(connection.execute(text("select current_database()")).scalar_one())
        raise RuntimeError("refused by the guard")

    monkeypatch.setattr("tests.integration.conftest.assert_disposable", refusing)
    try:
        with pytest.raises(RuntimeError, match="refused by the guard"):
            delete_user_rows(test_engine)
        with Session(test_engine) as session:
            kept = session.scalar(
                select(func.count()).select_from(User).where(User.email == email)
            )
    finally:
        monkeypatch.undo()
        delete_user_rows(test_engine)

    assert checked == [TEST_DATABASE_NAME]
    assert kept == 1


def test_closed_session_leaves_no_rows_behind(test_engine):
    email = "isolation-cleanup@example.com"
    with Session(test_engine) as session:
        session.add(User(email=email))
        session.flush()
    # closing the session without commit rolls the insert back

    with Session(test_engine) as session:
        count = session.scalar(select(func.count()).select_from(User).where(User.email == email))

    assert count == 0
