"""Safety checks for the integration-test database.

The integration tests are destructive: the service and API tests delete every user, plan and
session in their database before and after each test, and the migration tests move its schema down
and up again. So they run only in a database that exists to be emptied, and nowhere else:

- the approved target is `formiq_pytest`, on the server TEST_DATABASE_URL names (same host and
  credentials: nothing is added to .env). It is created by the tests the first time they run;
- `formiq_test` is NOT the target. It is the QA database: it holds accounts, plans and proposals
  made by hand and by the app's QA runs (Phase 2.6 found one, account 573, that nobody had made
  for a test), and a test run used to empty it. TEST_DATABASE_URL may still name `formiq_test`
  (that is what the setting held); the tests then use `formiq_pytest` on that server;
- the database carries a marker (its comment, DISPOSABLE_MARKER) that only these tests set, when
  they create it. Every destructive step first checks, on the connection it is about to use, that
  the database is the approved name AND carries the marker (assert_disposable): a database that
  was made for something else under the approved name is refused, never emptied.

Every check fails closed: anything unexpected raises RuntimeError and nothing is changed.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ProgrammingError

# The one database the tests may empty.
TEST_DATABASE_NAME = "formiq_pytest"
# What TEST_DATABASE_URL may name: the approved database itself, or `formiq_test` (what the setting
# held before Phase 2.7), which is only the address of the server: the tests never touch that database.
CONFIGURABLE_DATABASES = frozenset({TEST_DATABASE_NAME, "formiq_test"})
# Databases the tests never change, named so a message can say why
PROTECTED_DATABASES = {
    "formiq": "the development database",
    "formiq_test": "the QA database",
    "postgres": "the server's own database",
    "template0": "a template",
    "template1": "a template",
}
DISPOSABLE_MARKER = (
    "formiq automated tests: disposable, every row and table may be deleted at any time"
)
_MAINTENANCE_DATABASE = "postgres"


def check_test_database_url(test_database_url: str | None, database_url: str) -> str:
    """The URL of the database the tests may empty (TEST_DATABASE_NAME on the server
    TEST_DATABASE_URL names), or RuntimeError if TEST_DATABASE_URL is missing, is the development
    database, or names anything but the approved database (or `formiq_test`, only as the address of
    the server). No database is touched."""
    if not test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. The integration tests need a PostgreSQL server "
            f"to create the {TEST_DATABASE_NAME} database on (see 'Test database' in backend/README.md)."
        )
    configured = make_url(test_database_url)
    if configured.database == make_url(database_url).database:
        raise RuntimeError(
            "TEST_DATABASE_URL points to the same database as DATABASE_URL "
            f"({configured.database!r}). The integration tests must not use the "
            "development database."
        )
    if configured.database not in CONFIGURABLE_DATABASES:
        raise RuntimeError(
            f"TEST_DATABASE_URL must name the {TEST_DATABASE_NAME!r} database "
            f"(or 'formiq_test', as the server's address), not {configured.database!r}: the "
            "integration tests empty their database."
        )
    return configured.set(database=TEST_DATABASE_NAME).render_as_string(hide_password=False)


def assert_disposable(connection: Connection) -> None:
    """Raises RuntimeError unless the database this connection is in is the approved test database
    AND carries the marker only these tests set. Called before every step that deletes or
    migrates, on the connection that step will use, so what is checked is where it would act."""
    name, marker = connection.execute(
        text(
            "select current_database(), shobj_description(d.oid, 'pg_database') "
            "from pg_database d where d.datname = current_database()"
        )
    ).one()
    if name != TEST_DATABASE_NAME:
        reason = PROTECTED_DATABASES.get(name, "not the test database")
        raise RuntimeError(
            f"refusing to change database {name!r} ({reason}): the tests empty only "
            f"{TEST_DATABASE_NAME!r}"
        )
    if marker != DISPOSABLE_MARKER:
        raise RuntimeError(
            f"refusing to change database {name!r}: it is not marked as disposable by the tests "
            "(it was not created by them), so it may hold data that matters"
        )


def ensure_disposable_database(test_database_url: str) -> None:
    """Creates the approved test database and marks it, when it does not exist; otherwise only
    checks that it is the one the tests made (its marker). Raises RuntimeError for an existing
    database of that name that is not marked: it is never marked, changed or emptied here.

    test_database_url is what check_test_database_url returned. The database is created from the
    server's maintenance database, which the same login must be allowed to create databases in."""
    url = make_url(test_database_url)
    if url.database != TEST_DATABASE_NAME:
        raise RuntimeError(f"refusing to create {url.database!r}: not {TEST_DATABASE_NAME!r}")
    admin = create_engine(url.set(database=_MAINTENANCE_DATABASE), isolation_level="AUTOCOMMIT")

    def existing(connection: Connection) -> list:
        return connection.execute(
            text(
                "select shobj_description(oid, 'pg_database') "
                "from pg_database where datname = :name"
            ),
            {"name": TEST_DATABASE_NAME},
        ).all()

    try:
        with admin.connect() as connection:
            found = existing(connection)
            if not found:
                try:
                    # a constant, not user input: identifiers cannot be bound
                    connection.execute(text(f'create database "{TEST_DATABASE_NAME}"'))
                except ProgrammingError as error:
                    # another test process may have created it first: then it is there to check
                    if not existing(connection):
                        raise RuntimeError(
                            f"cannot create the {TEST_DATABASE_NAME!r} database: {error.orig}"
                        ) from error
                else:
                    # utility statements take no bound parameters: both values are constants
                    connection.exec_driver_sql(
                        f"comment on database \"{TEST_DATABASE_NAME}\" is '{DISPOSABLE_MARKER}'"
                    )
                found = existing(connection)
            if not found or found[0][0] != DISPOSABLE_MARKER:
                raise RuntimeError(
                    f"database {TEST_DATABASE_NAME!r} exists but is not marked as disposable by "
                    "the tests: it was made for something else, so it is not used and not "
                    "changed. Rename it or drop it yourself if it really is a test database."
                )
    finally:
        admin.dispose()
