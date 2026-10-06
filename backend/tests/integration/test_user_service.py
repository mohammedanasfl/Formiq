"""Integration tests for UserService.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user tables before
and after each test.
"""

from unittest.mock import patch

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.models import User
from app.schemas import UserCreate
from app.services import UserService
from app.services.exceptions import InvalidUserError, UserAlreadyExistsError

EMAIL = "user-service@example.com"
PHONE = "+910000000010"


@pytest.fixture
def service(service_session):
    return UserService(service_session)


def count_users(engine):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(User))


@pytest.mark.parametrize(
    "data",
    [{"email": EMAIL}, {"phone": PHONE}, {"email": EMAIL, "phone": PHONE}],
)
def test_create_user_commits_the_user(service, test_engine, data):
    user = service.create_user(UserCreate(**data))

    assert user.id is not None
    assert (user.email, user.phone) == (data.get("email"), data.get("phone"))
    with Session(test_engine) as other_session:  # committed, so visible to other sessions
        stored = other_session.get(User, user.id)
        assert (stored.email, stored.phone) == (data.get("email"), data.get("phone"))


def test_create_user_rejects_missing_email_and_phone(service, test_engine):
    # UserCreate itself rejects this; model_construct skips that validation
    with pytest.raises(InvalidUserError, match="email or phone is required"):
        service.create_user(UserCreate.model_construct(email=None, phone=None))

    assert count_users(test_engine) == 0


def test_create_user_rejects_duplicate_email(service, test_engine):
    service.create_user(UserCreate(email=EMAIL))

    with pytest.raises(UserAlreadyExistsError, match="email"):
        service.create_user(UserCreate(email=EMAIL, phone=PHONE))

    assert count_users(test_engine) == 1


def test_create_user_rejects_duplicate_phone(service, test_engine):
    service.create_user(UserCreate(phone=PHONE))

    with pytest.raises(UserAlreadyExistsError, match="phone"):
        service.create_user(UserCreate(email=EMAIL, phone=PHONE))

    assert count_users(test_engine) == 1


def test_users_without_email_or_phone_can_coexist(service, test_engine):
    # a missing email or phone is stored as NULL and is not a duplicate of
    # another user's missing value
    phones = [PHONE, "+910000000011"]
    emails = [EMAIL, f"second-{EMAIL}"]
    phone_only = [service.create_user(UserCreate(phone=phone)) for phone in phones]
    email_only = [service.create_user(UserCreate(email=email)) for email in emails]

    assert [user.email for user in phone_only] == [None, None]
    assert [user.phone for user in email_only] == [None, None]
    assert count_users(test_engine) == 4

    with pytest.raises(UserAlreadyExistsError, match="phone"):
        service.create_user(UserCreate(phone=PHONE))
    with pytest.raises(UserAlreadyExistsError, match="email"):
        service.create_user(UserCreate(email=EMAIL))

    assert count_users(test_engine) == 4


def test_get_user_by_id_returns_the_user(service, test_engine):
    user_id = service.create_user(UserCreate(email=EMAIL)).id

    with Session(test_engine) as other_session:
        user = UserService(other_session).get_user_by_id(user_id)
        assert user is not None
        assert user.email == EMAIL


def test_get_user_by_id_returns_none_for_missing_user(service):
    assert service.get_user_by_id(-1) is None


def test_create_user_commits_once(service, service_session):
    with patch.object(service_session, "commit", wraps=service_session.commit) as commit:
        service.create_user(UserCreate(email=EMAIL))

    commit.assert_called_once()


def test_rejected_create_rolls_back(service, service_session):
    service.create_user(UserCreate(email=EMAIL))

    with (
        patch.object(service_session, "commit", wraps=service_session.commit) as commit,
        patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback,
    ):
        with pytest.raises(UserAlreadyExistsError):
            service.create_user(UserCreate(email=EMAIL))

    commit.assert_not_called()
    rollback.assert_called_once()
    assert not service_session.in_transaction()


def test_failed_create_rolls_back(service, service_session, test_engine):
    # longer than the email column: model_construct skips the schema check, so the
    # insert itself fails in the database
    too_long = UserCreate.model_construct(email="a" * 300, phone=None)

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.create_user(too_long)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert count_users(test_engine) == 0
    # the session is usable again after the rollback
    assert service.create_user(UserCreate(email=EMAIL)).id is not None
