"""Integration tests: require the local PostgreSQL container to be running."""

from sqlalchemy import text


def test_database_connection(db_session):
    result = db_session.execute(text("SELECT 1")).scalar_one()

    assert result == 1
