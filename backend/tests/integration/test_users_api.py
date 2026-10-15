"""Integration tests for the /users API routes.

They require the local PostgreSQL container to be running. The client fixture
sends every request to the test database and empties the user tables before
and after each test.
"""

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User, UserProfile
from app.schemas import UserProfileResponse
from tests.auth import bearer
from tests.integration.users import create_user

EMAIL = "api-user@example.com"
PHONE = "+910000000020"


@pytest.fixture
def profile_body(profile_fields):
    return {
        **profile_fields,
        "last_name": "Rao",
        "target_weight_kg": 65.0,
        "goal_period_weeks": 12,
        "dietary_preference": "vegetarian",
    }


@pytest.fixture
def user_id(client, test_engine):
    return create_user(test_engine, email=EMAIL)


@pytest.fixture
def profile(client, user_id, profile_body):
    return client.post(f"/users/{user_id}/profile", json=profile_body).json()


def test_health_still_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# Users are made by signing up (POST /auth/register, test_registration_api.py)


@pytest.mark.parametrize(
    "body",
    [{"email": EMAIL}, {"phone": PHONE}, {"email": EMAIL, "phone": PHONE}, {}],
)
def test_no_route_creates_a_user(client, test_engine, body):
    # a user made without a password could never log in, and its email could
    # not sign up: no request creates one, signed in or not
    for headers in ({}, bearer(create_user(test_engine, email="signed-in@example.com"))):
        response = client.post("/users", json=body, headers=headers)

        assert response.status_code == 404
    with Session(test_engine) as session:
        assert session.scalars(select(User.email)).all() == ["signed-in@example.com"]


# GET /users/{user_id}


def test_get_user_returns_200_and_the_user(client, user_id):
    response = client.get(f"/users/{user_id}")

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert response.json()["email"] == EMAIL


def test_get_another_or_a_missing_user_returns_404(client, user_id, test_engine):
    other_user_id = create_user(test_engine, phone=PHONE)

    # the same answer whether or not the other user exists
    for other in (other_user_id, 999999):
        response = client.get(f"/users/{other}", headers=bearer(user_id))

        assert response.status_code == 404
        assert response.json() == {"detail": "not found"}


def test_get_user_with_invalid_id_returns_422(client, user_id):
    assert client.get("/users/abc", headers=bearer(user_id)).status_code == 422


@pytest.mark.parametrize("user_id", ["0", "-1", "2147483648"])
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/users/{}", None),
        ("post", "/users/{}/profile", "profile"),
        ("get", "/users/{}/profile", None),
        ("patch", "/users/{}/profile", {"weight_kg": 70.0}),
    ],
)
def test_user_id_outside_the_integer_column_range_returns_422(
    client, test_engine, profile_body, method, path, body, user_id
):
    json = profile_body if body == "profile" else body
    signed_in = create_user(test_engine, phone=PHONE)

    response = client.request(method, path.format(user_id), json=json, headers=bearer(signed_in))

    assert response.status_code == 422


def test_largest_integer_user_id_returns_404(client, user_id):
    assert client.get("/users/2147483647", headers=bearer(user_id)).status_code == 404


# POST /users/{user_id}/profile


def test_create_profile_returns_201_and_the_profile(client, user_id, profile_body, test_engine):
    response = client.post(f"/users/{user_id}/profile", json=profile_body)

    assert response.status_code == 201
    profile = response.json()
    assert set(profile) == set(UserProfileResponse.model_fields)
    UserProfileResponse.model_validate(profile)
    assert profile["user_id"] == user_id
    assert {key: profile[key] for key in profile_body} == profile_body
    with Session(test_engine) as session:
        assert session.get(UserProfile, profile["id"]).user_id == user_id


def test_create_profile_for_another_or_a_missing_user_returns_404(client, user_id, profile_body):
    response = client.post("/users/999999/profile", json=profile_body, headers=bearer(user_id))

    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}


def test_create_second_profile_returns_409(client, user_id, profile, profile_body):
    response = client.post(f"/users/{user_id}/profile", json=profile_body)

    assert response.status_code == 409
    assert response.json() == {"detail": f"user {user_id} already has a profile"}


@pytest.mark.parametrize(
    "change",
    [{"age": 0}, {"height_cm": -1}, {"first_name": ""}, {"first_name": None}],
)
def test_create_profile_with_invalid_body_returns_422(client, user_id, profile_body, change):
    response = client.post(f"/users/{user_id}/profile", json={**profile_body, **change})

    assert response.status_code == 422


def test_create_profile_without_required_field_returns_422(client, user_id, profile_body):
    del profile_body["weight_kg"]

    assert client.post(f"/users/{user_id}/profile", json=profile_body).status_code == 422


def test_create_profile_ignores_user_id_in_body(client, user_id, profile_body, test_engine):
    # UserProfileCreate does not declare user_id, so it is ignored, not rejected:
    # the profile belongs to the user in the path
    other_user_id = create_user(test_engine, phone=PHONE)

    response = client.post(
        f"/users/{user_id}/profile", json={**profile_body, "user_id": other_user_id}
    )

    assert response.status_code == 201
    assert response.json()["user_id"] == user_id
    with Session(test_engine) as session:
        assert session.get(UserProfile, response.json()["id"]).user_id == user_id
    assert client.get(f"/users/{other_user_id}/profile").status_code == 404


# GET /users/{user_id}/profile


def test_get_profile_returns_200_and_the_profile(client, user_id, profile):
    response = client.get(f"/users/{user_id}/profile")

    assert response.status_code == 200
    assert response.json() == profile


def test_get_profile_of_user_without_profile_returns_404(client, user_id):
    response = client.get(f"/users/{user_id}/profile")

    assert response.status_code == 404
    assert response.json() == {"detail": f"no profile found for user {user_id}"}


def test_get_profile_of_missing_user_returns_404(client, user_id):
    assert client.get("/users/999999/profile", headers=bearer(user_id)).status_code == 404


# PATCH /users/{user_id}/profile


def test_patch_profile_changes_only_supplied_fields(client, user_id, profile):
    response = client.patch(
        f"/users/{user_id}/profile", json={"weight_kg": 68.0, "goal": "build_muscle"}
    )

    assert response.status_code == 200
    updated = response.json()
    assert (updated["weight_kg"], updated["goal"]) == (68.0, "build_muscle")
    unchanged = set(profile) - {"weight_kg", "goal", "updated_at"}
    assert {key: updated[key] for key in unchanged} == {key: profile[key] for key in unchanged}
    assert client.get(f"/users/{user_id}/profile").json() == updated


def test_patch_profile_sets_nullable_field_to_null(client, user_id, profile):
    response = client.patch(f"/users/{user_id}/profile", json={"target_weight_kg": None})

    assert response.status_code == 200
    assert response.json()["target_weight_kg"] is None
    assert client.get(f"/users/{user_id}/profile").json()["target_weight_kg"] is None


def test_patch_profile_ignores_identity_and_timestamp_fields(
    client, user_id, profile, test_engine
):
    # UserProfileUpdate does not declare these fields, so they are ignored, not
    # rejected: only weight_kg changes
    other_user_id = create_user(test_engine, phone=PHONE)
    protected = {
        "id": profile["id"] + 1,
        "user_id": other_user_id,
        "created_at": "2000-01-01T00:00:00Z",
        "updated_at": "2000-01-01T00:00:00Z",
    }

    response = client.patch(f"/users/{user_id}/profile", json={**protected, "weight_kg": 68.0})

    assert response.status_code == 200
    updated = response.json()
    assert updated["weight_kg"] == 68.0
    unchanged = set(profile) - {"weight_kg", "updated_at"}
    assert {key: updated[key] for key in unchanged} == {key: profile[key] for key in unchanged}
    # updated_at is set by the database on update, not taken from the request
    updated_at = datetime.fromisoformat(updated["updated_at"])
    assert updated_at >= datetime.fromisoformat(profile["updated_at"])
    assert client.get(f"/users/{user_id}/profile").json() == updated
    assert client.get(f"/users/{other_user_id}/profile").status_code == 404


def test_patch_profile_with_null_required_field_returns_400(client, user_id, profile):
    response = client.patch(
        f"/users/{user_id}/profile", json={"weight_kg": 80.0, "first_name": None}
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "these fields cannot be null: first_name"}
    assert client.get(f"/users/{user_id}/profile").json() == profile


def test_patch_profile_of_user_without_profile_returns_404(client, user_id):
    response = client.patch(f"/users/{user_id}/profile", json={"weight_kg": 70.0})

    assert response.status_code == 404
    assert response.json() == {"detail": f"user {user_id} has no profile"}


def test_patch_profile_of_missing_user_returns_404(client, user_id):
    response = client.patch(
        "/users/999999/profile", json={"weight_kg": 70.0}, headers=bearer(user_id)
    )

    assert response.status_code == 404


@pytest.mark.parametrize("body", [{"age": 0}, {"age": "abc"}, {"sleep_hours": -1}])
def test_patch_profile_with_invalid_body_returns_422(client, user_id, profile, body):
    response = client.patch(f"/users/{user_id}/profile", json=body)

    assert response.status_code == 422
    assert client.get(f"/users/{user_id}/profile").json() == profile
