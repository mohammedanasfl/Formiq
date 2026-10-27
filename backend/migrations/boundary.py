"""Small hooks for validating an Alembic migration boundary.

The guard is injected through Alembic's Config attributes by the integration-test
configuration. Normal application migrations do not provide one and retain their
existing behavior.
"""

from collections.abc import Callable
from typing import Any


DATABASE_GUARD_ATTRIBUTE = "database_guard"


def run_guarded_migration(
    config: Any,
    connection: Any,
    migration: Callable[[], Any],
) -> Any:
    """Validate the actual connection before running an Alembic operation."""
    guard = config.attributes.get(DATABASE_GUARD_ATTRIBUTE)
    if guard is not None:
        was_in_transaction = connection.in_transaction()
        guard(connection)
        # The guard's query starts a transaction on the connection (autobegin). Alembic takes a
        # transaction that is already open for one the caller owns, and then never commits the
        # migration: it would run and be rolled back when the connection closes. End the one
        # the guard started, so the migration begins and commits its own.
        if not was_in_transaction and connection.in_transaction():
            connection.rollback()
    return migration()


def reject_guarded_offline_migration(config: Any) -> None:
    """Prevent test migrations from bypassing connection-based validation."""
    if config.attributes.get(DATABASE_GUARD_ATTRIBUTE) is not None:
        raise RuntimeError(
            "disposable-database migrations require an online connection so the target "
            "database and marker can be verified"
        )
