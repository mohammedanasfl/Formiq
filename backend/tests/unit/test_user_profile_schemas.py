from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import UserProfile
from app.schemas import UserProfileCreate, UserProfileResponse, UserProfileUpdate

VALID_PROFILE = {
    "first_name": "Asha",
    "last_name": "Rao",
    "age": 29,
    "height_cm": 165.0,
    "weight_kg": 62.5,
    "gender": "female",
    "fitness_experience": "beginner",
    "goal": "lose_weight",
    "target_weight_kg": 58.0,
    "goal_period_weeks": 12,
    "training_frequency_per_week": 3,
    "training_location": "home",
    "activity_level": "moderate",
    "sleep_hours": 7.5,
    "dietary_preference": "vegetarian",
}

OPTIONAL_FIELDS = {"last_name", "target_weight_kg", "goal_period_weeks", "dietary_preference"}


def test_user_profile_create_accepts_complete_profile():
    profile = UserProfileCreate.model_validate(VALID_PROFILE)

    assert profile.model_dump() == VALID_PROFILE


def test_user_profile_create_accepts_profile_without_optional_fields():
    data = {key: value for key, value in VALID_PROFILE.items() if key not in OPTIONAL_FIELDS}

    profile = UserProfileCreate.model_validate(data)

    assert all(getattr(profile, field) is None for field in OPTIONAL_FIELDS)


@pytest.mark.parametrize(
    "field",
    sorted(set(VALID_PROFILE) - OPTIONAL_FIELDS),
)
def test_user_profile_create_requires_non_nullable_fields(field):
    data = {key: value for key, value in VALID_PROFILE.items() if key != field}

    with pytest.raises(ValidationError):
        UserProfileCreate.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("age", 0),
        ("age", -1),
        ("height_cm", 0),
        ("weight_kg", 0),
        ("target_weight_kg", 0),
        ("goal_period_weeks", 0),
        ("sleep_hours", -1),
        ("training_frequency_per_week", -1),
        ("first_name", ""),
        ("gender", "x" * 51),
    ],
)
def test_user_profile_create_rejects_invalid_values(field, value):
    with pytest.raises(ValidationError):
        UserProfileCreate.model_validate({**VALID_PROFILE, field: value})


def test_user_profile_create_accepts_zero_sleep_and_training_frequency():
    profile = UserProfileCreate.model_validate(
        {**VALID_PROFILE, "sleep_hours": 0, "training_frequency_per_week": 0}
    )

    assert profile.sleep_hours == 0
    assert profile.training_frequency_per_week == 0


def test_user_profile_update_allows_empty_update():
    update = UserProfileUpdate.model_validate({})

    assert update.model_dump(exclude_unset=True) == {}


def test_user_profile_update_accepts_individual_fields():
    update = UserProfileUpdate.model_validate({"weight_kg": 61.0, "goal": "build_muscle"})

    assert update.model_dump(exclude_unset=True) == {"weight_kg": 61.0, "goal": "build_muscle"}


def test_user_profile_update_validates_supplied_fields():
    with pytest.raises(ValidationError):
        UserProfileUpdate.model_validate({"age": 0})


def test_user_profile_update_has_the_same_fields_as_create():
    assert set(UserProfileUpdate.model_fields) == set(UserProfileCreate.model_fields)


def test_user_profile_response_serializes_user_profile_model():
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    profile = UserProfile(
        id=1, user_id=2, **VALID_PROFILE, created_at=timestamp, updated_at=timestamp
    )

    response = UserProfileResponse.model_validate(profile)

    assert response.model_dump() == {
        "id": 1,
        "user_id": 2,
        **VALID_PROFILE,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def test_user_profile_schemas_match_user_profiles_columns():
    columns = set(UserProfile.__table__.columns.keys())

    assert set(UserProfileResponse.model_fields) == columns
    assert set(UserProfileCreate.model_fields) == columns - {"id", "user_id", "created_at", "updated_at"}
