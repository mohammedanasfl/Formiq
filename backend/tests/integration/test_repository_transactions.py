"""Integration tests for repository transaction behavior.

Repositories flush but never commit; the caller owns commit and rollback.
They require the local PostgreSQL container to be running.
"""

from unittest.mock import patch

from app.db.database import SessionLocal
from app.models import User, UserProfile
from app.repositories import UserProfileRepository, UserRepository

EMAIL = "transaction-test@example.com"


def test_repositories_never_commit(db_session, profile_fields):
    users = UserRepository(db_session)
    profiles = UserProfileRepository(db_session)

    with patch.object(db_session, "commit", wraps=db_session.commit) as commit:
        user = users.create(User(email=EMAIL, phone="+910000000002"))
        users.get_by_id(user.id)
        users.get_by_email(EMAIL)
        users.get_by_phone("+910000000002")
        profile = profiles.create(UserProfile(user=user, **profile_fields))
        profiles.get_by_id(profile.id)
        profiles.get_by_user_id(user.id)
        profile.sleep_hours = 8.0
        profiles.update(profile)
        profiles.delete(profile)
        users.delete(user)

    commit.assert_not_called()


def test_flushed_changes_are_not_visible_to_other_sessions(db_session):
    user = UserRepository(db_session).create(User(email=EMAIL))

    with SessionLocal() as other_session:
        assert UserRepository(other_session).get_by_id(user.id) is None

    assert db_session.in_transaction()


def test_caller_rollback_discards_repository_changes(db_session):
    users = UserRepository(db_session)
    user_id = users.create(User(email=EMAIL)).id

    db_session.rollback()

    assert users.get_by_id(user_id) is None


def test_caller_commit_persists_repository_changes(db_session):
    users = UserRepository(db_session)
    user = users.create(User(email=EMAIL))
    db_session.commit()

    try:
        with SessionLocal() as other_session:
            assert UserRepository(other_session).get_by_email(EMAIL) is not None
    finally:
        users.delete(user)
        db_session.commit()

    with SessionLocal() as other_session:
        assert UserRepository(other_session).get_by_email(EMAIL) is None
