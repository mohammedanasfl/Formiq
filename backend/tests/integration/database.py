"""Safety check for the integration-test database."""

from sqlalchemy.engine import make_url

TEST_DATABASE_NAME = "formiq_test"


def check_test_database_url(test_database_url: str | None, database_url: str) -> str:
    """Return TEST_DATABASE_URL, or raise RuntimeError if it is unsafe to use.

    The integration tests change and drop data, so they must never run against
    the development database (DATABASE_URL).
    """
    if not test_database_url:
        raise RuntimeError(
            "TEST_DATABASE_URL is not set. The integration tests need the "
            f"{TEST_DATABASE_NAME} database (see 'Test database' in backend/README.md)."
        )

    test_database = make_url(test_database_url).database
    if test_database == make_url(database_url).database:
        raise RuntimeError(
            "TEST_DATABASE_URL points to the same database as DATABASE_URL "
            f"({test_database!r}). The integration tests must not use the "
            "development database."
        )
    if test_database != TEST_DATABASE_NAME:
        raise RuntimeError(
            f"TEST_DATABASE_URL must point to the {TEST_DATABASE_NAME!r} database, "
            f"not {test_database!r}."
        )

    return test_database_url
