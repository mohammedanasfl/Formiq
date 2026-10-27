import pytest

from migrations.boundary import (
    DATABASE_GUARD_ATTRIBUTE,
    reject_guarded_offline_migration,
    run_guarded_migration,
)
from tests.integration.database import (
    DISPOSABLE_MARKER,
    TEST_DATABASE_NAME,
    assert_disposable,
)


class Config:
    def __init__(self, **attributes):
        self.attributes = attributes


class Result:
    def __init__(self, row):
        self.row = row

    def one(self):
        return self.row


class Connection:
    """A connection as SQLAlchemy 2 has one: a statement starts a transaction (autobegin)
    when none is open, and it stays open until rolled back or committed."""

    def __init__(self, name, marker, *, in_transaction=False):
        self.name = name
        self.marker = marker
        self.open = in_transaction
        self.rollbacks = 0

    def execute(self, statement):
        self.open = True
        return Result((self.name, self.marker))

    def in_transaction(self):
        return self.open

    def rollback(self):
        self.open = False
        self.rollbacks += 1


def disposable_config():
    return Config(**{DATABASE_GUARD_ATTRIBUTE: assert_disposable})


def test_online_boundary_accepts_the_marked_disposable_database():
    ran = []

    run_guarded_migration(
        disposable_config(),
        Connection(TEST_DATABASE_NAME, DISPOSABLE_MARKER),
        lambda: ran.append(True),
    )

    assert ran == [True]


@pytest.mark.parametrize(
    ("name", "marker"),
    [
        ("formiq", DISPOSABLE_MARKER),
        (TEST_DATABASE_NAME, None),
        (TEST_DATABASE_NAME, "incorrect marker"),
    ],
)
def test_online_boundary_rejects_wrong_or_unmarked_databases(name, marker):
    ran = []

    with pytest.raises(RuntimeError):
        run_guarded_migration(
            disposable_config(), Connection(name, marker), lambda: ran.append(True)
        )

    assert ran == []


@pytest.mark.parametrize("operation", ["upgrade", "downgrade"])
def test_online_migration_guard_runs_before_each_operation(operation):
    events = []
    connection = Connection(TEST_DATABASE_NAME, DISPOSABLE_MARKER)

    def guard(received_connection):
        assert received_connection is connection
        events.append("guard")

    config = Config(**{DATABASE_GUARD_ATTRIBUTE: guard})

    run_guarded_migration(config, connection, lambda: events.append(operation))

    assert events == ["guard", operation]


def test_the_transaction_the_guard_started_is_ended_before_the_migration_runs():
    # Alembic takes an open transaction for the caller's and never commits the migration in it
    connection = Connection(TEST_DATABASE_NAME, DISPOSABLE_MARKER)
    open_during_migration = []

    run_guarded_migration(
        disposable_config(),
        connection,
        lambda: open_during_migration.append(connection.in_transaction()),
    )

    assert open_during_migration == [False]
    assert connection.rollbacks == 1


def test_a_transaction_the_caller_began_is_left_open():
    connection = Connection(TEST_DATABASE_NAME, DISPOSABLE_MARKER, in_transaction=True)
    open_during_migration = []

    run_guarded_migration(
        disposable_config(),
        connection,
        lambda: open_during_migration.append(connection.in_transaction()),
    )

    assert open_during_migration == [True]
    assert connection.rollbacks == 0


@pytest.mark.parametrize("attributes", [{}, {DATABASE_GUARD_ATTRIBUTE: None}])
def test_normal_migrations_do_not_require_the_test_guard(attributes):
    events = []

    run_guarded_migration(Config(**attributes), object(), lambda: events.append("migration"))

    assert events == ["migration"]


def test_offline_test_migrations_fail_closed():
    config = Config(**{DATABASE_GUARD_ATTRIBUTE: lambda connection: None})

    with pytest.raises(RuntimeError, match="require an online connection"):
        reject_guarded_offline_migration(config)


def test_normal_offline_migrations_remain_supported():
    reject_guarded_offline_migration(Config())
