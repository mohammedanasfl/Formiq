"""Integration tests for UserProfileRepository.

They require the local PostgreSQL container to be running. Each test runs in a
transaction that the db_session fixture rolls back.
"""

import pytest

from app.models import User, UserProfile
from app.repositories import UserProfileRepository, UserRepository


@pytest.fixture
def user(db_session):
    return UserRepository(db_session).create(User(email="profile-repository@example.com"))


@pytest.fixture
def profiles(db_session):
    return UserProfileRepository(db_session)


def test_create_persists_profile_and_assigns_id(profiles, user, profile_fields, db_session):
    profile = profiles.create(UserProfile(user=user, **profile_fields))

    assert profile.id is not None
    assert profile.user_id == user.id
    assert not db_session.new  # flushed to the database


def test_get_by_id_returns_profile(profiles, user, profile_fields, db_session):
    profile_id = profiles.create(UserProfile(user=user, **profile_fields)).id
    db_session.expunge_all()  # read from the database, not the session's identity map

    profile = profiles.get_by_id(profile_id)

    assert profile is not None
    assert profile.first_name == profile_fields["first_name"]


def test_get_by_user_id_returns_profile_of_that_user(profiles, user, profile_fields, db_session):
    profile_id = profiles.create(UserProfile(user=user, **profile_fields)).id
    user_id = user.id
    db_session.expunge_all()

    profile = profiles.get_by_user_id(user_id)

    assert profile is not None
    assert profile.id == profile_id
    assert profile.user.id == user_id
    assert profile.user.profile is profile


def test_get_by_id_returns_none_for_missing_profile(profiles):
    assert profiles.get_by_id(-1) is None


def test_get_by_user_id_returns_none_when_user_has_no_profile(profiles, user):
    assert profiles.get_by_user_id(user.id) is None


def test_update_persists_changes(profiles, user, profile_fields, db_session):
    profile = profiles.create(UserProfile(user=user, **profile_fields))
    profile_id = profile.id
    profile.weight_kg = 68.5
    profile.goal = "build_muscle"

    updated = profiles.update(profile)

    assert updated is profile
    assert not db_session.dirty  # flushed to the database
    db_session.expunge_all()
    reloaded = profiles.get_by_id(profile_id)
    assert reloaded.weight_kg == 68.5
    assert reloaded.goal == "build_muscle"


def test_delete_removes_profile_but_keeps_user(profiles, user, profile_fields, db_session):
    profile = profiles.create(UserProfile(user=user, **profile_fields))
    profile_id, user_id = profile.id, user.id

    profiles.delete(profile)
    db_session.expunge_all()

    assert profiles.get_by_id(profile_id) is None
    assert profiles.get_by_user_id(user_id) is None
    assert UserRepository(db_session).get_by_id(user_id) is not None
