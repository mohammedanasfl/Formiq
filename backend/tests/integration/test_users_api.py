"""Integration tests for the /users API routes.

They require the local PostgreSQL container to be running. The client fixture
sends every request to the test database and empties the user tables before
and after each test.
"""

import pytest
from sqlalchemy.orm import Session

from app.models import User, UserProfile
from app.schemas import UserProfileResponse, UserResponse

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
def user_id(client):
    return client.post("/users", json={"email": EMAIL}).json()["id"]


@pytest.fixture
def profile(client, user_id, profile_body):
    return client.post(f"/users/{user_id}/profile", json=profile_body).json()


def test_health_still_returns_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# POST /users


@pytest.mark.parametrize(
    "body",
    [{"email": EMAIL}, {"phone": PHONE}, {"email": EMAIL, "phone": PHONE}],
)
def test_create_user_returns_201_and_the_user(client, body):
    response = client.post("/users", json=body)

    assert response.status_code == 201
    user = response.json()
    assert set(user) == set(UserResponse.model_fields)
    UserResponse.model_validate(user)
    assert (user["email"], user["phone"]) == (body.get("email"), body.get("phone"))


def test_create_user_persists_the_user_in_the_test_database(client, test_engine):
    user_id = client.post("/users", json={"email": EMAIL}).json()["id"]

    with Session(test_engine) as session:
        assert session.get(User, user_id).email == EMAIL


@pytest.mark.parametrize("body", [{}, {"email": None, "phone": None}])
def test_create_user_without_email_or_phone_returns_422(client, body):
    assert client.post("/users", json=body).status_code == 422


def test_create_user_with_duplicate_email_returns_409(client):
    client.post("/users", json={"email": EMAIL})

    response = client.post("/users", json={"email": EMAIL, "phone": PHONE})

    assert response.status_code == 409
    assert response.json() == {"detail": "a user with this email already exists"}


def test_create_user_with_duplicate_phone_returns_409(client):
    client.post("/users", json={"phone": PHONE})

    response = client.post("/users", json={"email": EMAIL, "phone": PHONE})

    assert response.status_code == 409
    assert response.json() == {"detail": "a user with this phone already exists"}


# GET /users/{user_id}


def test_get_user_returns_200_and_the_user(client, user_id):
    response = client.get(f"/users/{user_id}")

    assert response.status_code == 200
    assert response.json()["id"] == user_id
    assert response.json()["email"] == EMAIL


def test_get_missing_user_returns_404(client):
    response = client.get("/users/999999")

    assert response.status_code == 404
    assert response.json() == {"detail": "user 999999 does not exist"}


def test_get_user_with_invalid_id_returns_422(client):
    assert client.get("/users/abc").status_code == 422


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
    client, profile_body, method, path, body, user_id
):
    json = profile_body if body == "profile" else body

    response = client.request(method, path.format(user_id), json=json)

    assert response.status_code == 422


def test_largest_integer_user_id_returns_404(client):
    assert client.get("/users/2147483647").status_code == 404


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


def test_create_profile_for_missing_user_returns_404(client, profile_body):
    response = client.post("/users/999999/profile", json=profile_body)

    assert response.status_code == 404
    assert response.json() == {"detail": "user 999999 does not exist"}


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


# GET /users/{user_id}/profile


def test_get_profile_returns_200_and_the_profile(client, user_id, profile):
    response = client.get(f"/users/{user_id}/profile")

    assert response.status_code == 200
    assert response.json() == profile


def test_get_profile_of_user_without_profile_returns_404(client, user_id):
    response = client.get(f"/users/{user_id}/profile")

    assert response.status_code == 404
    assert response.json() == {"detail": f"no profile found for user {user_id}"}


def test_get_profile_of_missing_user_returns_404(client):
    assert client.get("/users/999999/profile").status_code == 404


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


def test_patch_profile_of_missing_user_returns_404(client):
    assert client.patch("/users/999999/profile", json={"weight_kg": 70.0}).status_code == 404


@pytest.mark.parametrize("body", [{"age": 0}, {"age": "abc"}, {"sleep_hours": -1}])
def test_patch_profile_with_invalid_body_returns_422(client, user_id, profile, body):
    response = client.patch(f"/users/{user_id}/profile", json=body)

    assert response.status_code == 422
    assert client.get(f"/users/{user_id}/profile").json() == profile
