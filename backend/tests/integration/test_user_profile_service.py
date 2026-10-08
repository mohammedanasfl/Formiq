"""Integration tests for UserProfileService.

They require the local PostgreSQL container to be running (test database).
Services commit, so the service_session fixture empties the user tables before
and after each test.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app.models import UserProfile
from app.repositories import UserProfileRepository
from app.schemas import UserCreate, UserProfileCreate, UserProfileUpdate
from app.services import UserProfileService, UserService
from app.services.exceptions import (
    InvalidProfileUpdateError,
    UserNotFoundError,
    UserProfileAlreadyExistsError,
    UserProfileNotFoundError,
)
from app.services.user_profile_service import REQUIRED_PROFILE_FIELDS


@pytest.fixture
def service(service_session):
    return UserProfileService(service_session)


@pytest.fixture
def user(service_session):
    return UserService(service_session).create_user(UserCreate(email="profile-service@example.com"))


@pytest.fixture
def profile_data(profile_fields):
    return UserProfileCreate(
        **profile_fields,
        last_name="Rao",
        target_weight_kg=65.0,
        goal_period_weeks=12,
        dietary_preference="vegetarian",
    )


def stored_profile(engine, user_id):
    """The profile's columns as committed in the database."""
    with Session(engine) as session:
        profile = UserProfileRepository(session).get_by_user_id(user_id)
        return {column.key: getattr(profile, column.key) for column in UserProfile.__table__.columns}


def count_profiles(engine):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(UserProfile))


def test_create_profile_commits_the_profile(service, user, profile_data, test_engine):
    profile = service.create_profile(user.id, profile_data)

    assert profile.id is not None
    assert profile.user_id == user.id
    stored = stored_profile(test_engine, user.id)  # committed, so visible to other sessions
    assert {key: stored[key] for key in profile_data.model_dump()} == profile_data.model_dump()


def test_create_profile_rejects_missing_user(service, profile_data, test_engine):
    with pytest.raises(UserNotFoundError):
        service.create_profile(-1, profile_data)

    assert count_profiles(test_engine) == 0


def test_create_profile_rejects_second_profile(service, user, profile_data, test_engine):
    service.create_profile(user.id, profile_data)
    second = profile_data.model_copy(update={"first_name": "Second"})

    with pytest.raises(UserProfileAlreadyExistsError):
        service.create_profile(user.id, second)

    assert count_profiles(test_engine) == 1
    assert stored_profile(test_engine, user.id)["first_name"] == profile_data.first_name


def test_failed_create_profile_rolls_back(
    service, service_session, user, profile_data, test_engine
):
    # longer than the first_name column: model_copy skips the schema check, so the
    # database rejects the insert when the repository flushes the profile
    too_long = profile_data.model_copy(update={"first_name": "x" * 101})

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.create_profile(user.id, too_long)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert count_profiles(test_engine) == 0
    # the session is usable again after the rollback
    profile = service.create_profile(user.id, profile_data)
    assert stored_profile(test_engine, user.id)["id"] == profile.id


def test_get_profile_by_user_id_returns_the_profile(service, user, profile_data):
    profile_id = service.create_profile(user.id, profile_data).id

    assert service.get_profile_by_user_id(user.id).id == profile_id


def test_get_profile_by_user_id_returns_none_without_profile(service, user):
    assert service.get_profile_by_user_id(user.id) is None


def test_update_profile_changes_only_supplied_fields(service, user, profile_data, test_engine):
    service.create_profile(user.id, profile_data)
    before = stored_profile(test_engine, user.id)

    service.update_profile(user.id, UserProfileUpdate(weight_kg=68.0, goal="build_muscle"))

    after = stored_profile(test_engine, user.id)
    assert (after["weight_kg"], after["goal"]) == (68.0, "build_muscle")
    unchanged = set(before) - {"weight_kg", "goal", "updated_at"}
    assert {key: after[key] for key in unchanged} == {key: before[key] for key in unchanged}


def test_update_profile_sets_nullable_fields_to_null(service, user, profile_data, test_engine):
    service.create_profile(user.id, profile_data)
    nullable = ["last_name", "target_weight_kg", "goal_period_weeks", "dietary_preference"]

    service.update_profile(user.id, UserProfileUpdate(**{field: None for field in nullable}))

    after = stored_profile(test_engine, user.id)
    assert {field: after[field] for field in nullable} == {field: None for field in nullable}
    assert after["first_name"] == profile_data.first_name


def test_update_profile_refreshes_updated_at(service, user, profile_data, test_engine):
    service.create_profile(user.id, profile_data)
    # move both timestamps into the past, so the update's new updated_at is later
    # without waiting for the clock to advance
    past = datetime(2000, 1, 1, tzinfo=timezone.utc)
    with Session(test_engine) as session:
        session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user.id)
            .values(created_at=past, updated_at=past)
        )
        session.commit()
    before = stored_profile(test_engine, user.id)

    profile = service.update_profile(user.id, UserProfileUpdate(weight_kg=68.0))

    after = stored_profile(test_engine, user.id)
    assert after["weight_kg"] == 68.0
    assert after["updated_at"] > before["updated_at"]
    assert after["created_at"] == before["created_at"]
    assert (profile.created_at, profile.updated_at) == (after["created_at"], after["updated_at"])


@pytest.mark.parametrize("field", sorted(REQUIRED_PROFILE_FIELDS))
def test_update_profile_rejects_null_for_required_field(service, user, profile_data, field):
    service.create_profile(user.id, profile_data)

    with pytest.raises(InvalidProfileUpdateError, match=field):
        service.update_profile(user.id, UserProfileUpdate(**{field: None}))


def test_rejected_update_leaves_profile_unchanged(
    service, service_session, user, profile_data, test_engine
):
    service.create_profile(user.id, profile_data)
    before = stored_profile(test_engine, user.id)
    # a valid change together with a null for a required field
    update = UserProfileUpdate(weight_kg=80.0, first_name=None)

    with (
        patch.object(service_session, "commit", wraps=service_session.commit) as commit,
        patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback,
    ):
        with pytest.raises(InvalidProfileUpdateError):
            service.update_profile(user.id, update)

    commit.assert_not_called()
    rollback.assert_called_once()
    assert stored_profile(test_engine, user.id) == before


def test_update_profile_rejects_missing_profile(service, user):
    with pytest.raises(UserProfileNotFoundError):
        service.update_profile(user.id, UserProfileUpdate(weight_kg=70.0))


def test_failed_update_rolls_back(service, service_session, user, profile_data, test_engine):
    service.create_profile(user.id, profile_data)
    before = stored_profile(test_engine, user.id)
    # longer than the first_name column: model_construct skips the schema check, so
    # the update itself fails in the database
    too_long = UserProfileUpdate.model_construct(weight_kg=80.0, first_name="x" * 101)

    with patch.object(service_session, "rollback", wraps=service_session.rollback) as rollback:
        with pytest.raises(DataError):
            service.update_profile(user.id, too_long)

    rollback.assert_called_once()
    assert not service_session.in_transaction()
    assert stored_profile(test_engine, user.id) == before
    # the session is usable again after the rollback
    assert service.update_profile(user.id, UserProfileUpdate(weight_kg=69.0)).weight_kg == 69.0


def test_profile_mutations_commit_once_each(service, service_session, user, profile_data):
    with patch.object(service_session, "commit", wraps=service_session.commit) as commit:
        service.create_profile(user.id, profile_data)
        assert commit.call_count == 1

        service.update_profile(user.id, UserProfileUpdate(sleep_hours=8.0))
        assert commit.call_count == 2
