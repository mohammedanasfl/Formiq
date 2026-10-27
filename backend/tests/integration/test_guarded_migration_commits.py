"""A migration run through the disposable-database guard is committed.

The guard (migrations.boundary, with assert_disposable) queries the connection before
Alembic configures itself on it. That query starts a transaction on the connection, and
Alembic takes a transaction that is already open for one its caller owns: it ran the
migration inside it and never committed, so the upgrade was logged and then rolled back
when the connection closed, and the test database never moved. Unit tests with fake
connections cannot see that: this one reads the database's revision from a separate
connection after each step.

It moves the disposable database's schema down one revision and up again, as the other
migration tests do, so it runs alone in its module: the downgrade needs locks that an open
transaction in the same module would hold.
"""

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import text

from tests.integration.database import assert_disposable


def current_revision(engine):
    """The revision the database holds, read in a new transaction on a separate connection."""
    with engine.connect() as connection:
        assert_disposable(connection)
        return connection.execute(text("select version_num from alembic_version")).scalar_one()


def test_a_guarded_downgrade_and_upgrade_are_committed(test_engine, test_alembic_config):
    script = ScriptDirectory.from_config(test_alembic_config)
    head = script.get_current_head()
    previous = script.get_revision(head).down_revision
    assert isinstance(previous, str)
    # test_engine upgraded to head through the guard: that must have persisted
    assert current_revision(test_engine) == head

    try:
        command.downgrade(test_alembic_config, "-1")
        assert current_revision(test_engine) == previous
    finally:
        command.upgrade(test_alembic_config, "head")

    assert current_revision(test_engine) == head
