"""Access tokens for tests: signed with a test-only secret, never a real one.

The integration tests' application verifies tokens with TEST_ACCESS_TOKENS
(tests/integration/conftest.py), so bearer(user_id) signs a request in as
that user.
"""

from app.core.security import AccessTokens

TEST_ACCESS_TOKENS = AccessTokens("test-only-signing-secret-never-used-for-real")


def bearer(user_id: int) -> dict[str, str]:
    """The Authorization header of a request signed in as the user."""
    return {"Authorization": f"Bearer {TEST_ACCESS_TOKENS.issue(user_id)}"}
