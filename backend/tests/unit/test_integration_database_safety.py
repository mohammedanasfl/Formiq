import pytest

from tests.integration.database import (
    DISPOSABLE_MARKER,
    TEST_DATABASE_NAME,
    assert_disposable,
    check_test_database_url,
    ensure_disposable_database,
)

SERVER = "postgresql+psycopg://test-user:test-password@localhost:5432"
DEV_URL = f"{SERVER}/formiq"


class Result:
    def __init__(self, rows):
        self.rows = rows

    def one(self):
        return self.rows[0]

    def all(self):
        return self.rows


class Connection:
    def __init__(self, answers):
        self.answers = list(answers)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append(sql)
        if sql.startswith("create database"):
            return Result([])
        return Result(self.answers.pop(0) if self.answers else [])

    def exec_driver_sql(self, statement):
        self.statements.append(statement)
        return Result([])


class Engine:
    def __init__(self, connection):
        self.connection = connection
        self.disposed = False

    def connect(self):
        return self.connection

    def dispose(self):
        self.disposed = True


def test_check_rewrites_qa_database_to_the_disposable_target():
    url = check_test_database_url(f"{SERVER}/formiq_test", DEV_URL)

    assert url.endswith(f"/{TEST_DATABASE_NAME}")
    assert "formiq_test" not in url


@pytest.mark.parametrize("database", ["formiq", "postgres", "template1", "unknown"])
def test_check_rejects_protected_or_unknown_database_names(database):
    with pytest.raises(RuntimeError):
        check_test_database_url(f"{SERVER}/{database}", DEV_URL)


@pytest.mark.parametrize("name", ["formiq", "formiq_test", "postgres", "template0", "unknown"])
def test_connection_guard_rejects_non_disposable_database(name):
    connection = Connection([[(name, DISPOSABLE_MARKER)]])

    with pytest.raises(RuntimeError):
        assert_disposable(connection)


def test_connection_guard_requires_the_exact_marker():
    connection = Connection([[(TEST_DATABASE_NAME, "not disposable")]])

    with pytest.raises(RuntimeError, match="not marked as disposable"):
        assert_disposable(connection)


def test_ensure_uses_only_the_maintenance_database_and_marks_a_missing_target(monkeypatch):
    connection = Connection([[], [(DISPOSABLE_MARKER,)]])
    engine = Engine(connection)
    seen = {}

    def fake_create_engine(url, **kwargs):
        seen["database"] = url.database
        seen["isolation_level"] = kwargs["isolation_level"]
        return engine

    monkeypatch.setattr("tests.integration.database.create_engine", fake_create_engine)
    ensure_disposable_database(f"{SERVER}/{TEST_DATABASE_NAME}")

    assert seen == {"database": "postgres", "isolation_level": "AUTOCOMMIT"}
    assert f'create database "{TEST_DATABASE_NAME}"' in connection.statements
    assert engine.disposed
