"""Integration tests for UserRepository.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

import pytest
from psycopg.errors import NotNullViolation
from sqlalchemy.exc import IntegrityError

from app.models import User, UserProfile
from app.repositories import UserProfileRepository, UserRepository

EMAIL = "user-repository@example.com"
PHONE = "+910000000001"


@pytest.fixture
def users(db_session):
    return UserRepository(db_session)


def test_create_persists_user_and_assigns_id(users, db_session):
    user = users.create(User(email=EMAIL, phone=PHONE))

    assert user.id is not None
    assert user.created_at is not None
    assert not db_session.new  # flushed to the database


def test_get_by_id_returns_user(users, db_session):
    user_id = users.create(User(email=EMAIL)).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    user = users.get_by_id(user_id)

    assert user is not None
    assert user.email == EMAIL


def test_get_by_email_returns_user(users, db_session):
    user_id = users.create(User(email=EMAIL)).id
    db_session.expunge_all()

    user = users.get_by_email(EMAIL)

    assert user is not None
    assert user.id == user_id


def test_get_by_phone_returns_user(users, db_session):
    user_id = users.create(User(phone=PHONE)).id
    db_session.expunge_all()

    user = users.get_by_phone(PHONE)

    assert user is not None
    assert user.id == user_id


def test_get_by_id_returns_none_for_missing_user(users):
    assert users.get_by_id(-1) is None


def test_get_by_email_returns_none_for_missing_email(users):
    assert users.get_by_email("missing@example.com") is None


def test_get_by_phone_returns_none_for_missing_phone(users):
    assert users.get_by_phone("+910000000000") is None


def test_delete_removes_user(users, db_session):
    user = users.create(User(email=EMAIL))
    user_id = user.id

    users.delete(user)
    db_session.expunge_all()

    assert users.get_by_id(user_id) is None


def test_delete_user_with_profile_fails_without_cascade(users, db_session, profile_fields):
    user = users.create(User(email=EMAIL))
    UserProfileRepository(db_session).create(UserProfile(user=user, **profile_fields))

    with pytest.raises(IntegrityError) as error:
        users.delete(user)

    assert isinstance(error.value.orig, NotNullViolation)
