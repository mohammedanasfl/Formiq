from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models import User
from app.schemas import UserCreate, UserResponse

EMAIL = "user@example.com"
PHONE = "+919999999999"


@pytest.mark.parametrize(
    "data",
    [
        {"email": EMAIL},
        {"phone": PHONE},
        {"email": EMAIL, "phone": PHONE},
    ],
)
def test_user_create_accepts_email_phone_or_both(data):
    user = UserCreate.model_validate(data)

    assert user.email == data.get("email")
    assert user.phone == data.get("phone")


@pytest.mark.parametrize("data", [{}, {"email": None, "phone": None}])
def test_user_create_requires_email_or_phone(data):
    with pytest.raises(ValidationError, match="email or phone is required"):
        UserCreate.model_validate(data)


@pytest.mark.parametrize(
    "data",
    [
        {"email": ""},
        {"phone": ""},
        {"email": "a" * 256},
        {"phone": "1" * 31},
    ],
)
def test_user_create_rejects_empty_or_too_long_values(data):
    with pytest.raises(ValidationError):
        UserCreate.model_validate(data)


def test_user_response_serializes_user_model():
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    user = User(id=1, email=EMAIL, phone=None, created_at=timestamp, updated_at=timestamp)

    response = UserResponse.model_validate(user)

    assert response.model_dump() == {
        "id": 1,
        "email": EMAIL,
        "phone": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def test_user_response_fields_match_users_columns():
    assert set(UserResponse.model_fields) == set(User.__table__.columns.keys())
