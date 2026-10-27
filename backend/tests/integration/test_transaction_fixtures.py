"""The fixtures that keep a test's changes in a transaction that is rolled back
(rollback_connection, and imported_catalog which the catalog tests build on) start the
transaction first and check the database inside it.

assert_disposable queries the connection, which starts a transaction (autobegin), and
Connection.begin() refuses a connection that is already in one: with the check before
begin(), these fixtures failed in setup and no test that used them could run.
"""

import pytest

from tests.integration.database import assert_disposable


@pytest.mark.parametrize("fixture", ["rollback_connection", "imported_catalog"])
def test_a_transaction_fixture_checks_the_database_inside_its_transaction(fixture, request):
    value = request.getfixturevalue(fixture)
    # imported_catalog holds its connection; rollback_connection is the connection
    connection = value.connection if fixture == "imported_catalog" else value

    assert connection.in_transaction()
    # still the approved database, still marked: the check holds on the connection in use
    assert_disposable(connection)
