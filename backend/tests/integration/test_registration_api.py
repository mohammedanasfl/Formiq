"""Signing up (POST /auth/register) and logging in with the email it was made
with, through the API on the test database.

An account is made only by signing up, which gives it its password: no request
can make a user without one, so no one can take an email before its owner
signs up with it. An email is one account whatever its case
(app.core.emails): sign-up stores it normalized and refuses it in any case,
and login matches it so. Accounts made before that may differ only in case:
they are kept apart, never merged.

They require the local PostgreSQL container to be running. Tokens are signed
with the test-only secret (tests/auth.py); the passwords are test-only values.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import User, UserCredential
from app.services import AuthService
from tests.auth import TEST_ACCESS_TOKENS, bearer
from tests.integration.users import create_user

EMAIL = "asha.rao@example.com"
PASSWORD = "test-only password one"
OTHER_PASSWORD = "test-only password two"
ACCOUNT_EXISTS = {"detail": "an account with this email already exists"}
REFUSED_LOGIN = {"detail": "invalid email or password"}


@pytest.fixture
def client(client):
    # every request here says for itself who it is signed in as
    client.sign_in_path_user = False
    return client


def register(client, email, password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client, email, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def user_of(response) -> int:
    assert response.status_code in (200, 201), response.json()
    return TEST_ACCESS_TOKENS.verify(response.json()["access_token"])


def stored_users(engine) -> list[tuple[str | None, bool]]:
    """Each user's email, and whether it has a password, by id."""
    with Session(engine) as session:
        rows = session.execute(
            select(User.email, UserCredential.user_id.is_not(None))
            .outerjoin(UserCredential, UserCredential.user_id == User.id)
            .order_by(User.id)
        )
        return [tuple(row) for row in rows]


# --- no one takes an email before its owner signs up ---


def test_an_anonymous_request_cannot_reserve_an_email(client, test_engine):
    taken = client.post("/users", json={"email": EMAIL})

    assert taken.status_code == 404
    assert stored_users(test_engine) == []
    # the owner of the email still signs up, and logs in with it
    user_id = user_of(register(client, EMAIL))
    assert user_of(login(client, EMAIL)) == user_id
    assert stored_users(test_engine) == [(EMAIL, True)]


def test_signing_up_creates_an_account_signed_in_as_itself(client, test_engine):
    response = register(client, EMAIL)

    assert response.status_code == 201
    assert response.json()["token_type"] == "bearer"
    user_id = user_of(response)
    own = client.get(f"/users/{user_id}", headers=bearer(user_id))
    assert (own.status_code, own.json()["email"]) == (200, EMAIL)
    assert stored_users(test_engine) == [(EMAIL, True)]


def test_an_email_is_stored_in_lower_case_without_spaces(client, test_engine):
    user_id = user_of(register(client, "  Asha.Rao@Example.COM "))

    assert stored_users(test_engine) == [(EMAIL, True)]
    assert user_of(login(client, EMAIL)) == user_id


@pytest.mark.parametrize("email", [EMAIL, EMAIL.upper(), "Asha.Rao@example.com", f" {EMAIL}"])
def test_an_email_with_an_account_is_refused_in_any_case(client, test_engine, email):
    user_id = user_of(register(client, EMAIL))

    response = register(client, email, OTHER_PASSWORD)

    assert (response.status_code, response.json()) == (409, ACCOUNT_EXISTS)
    assert "access_token" not in response.json()
    assert stored_users(test_engine) == [(EMAIL, True)]
    # the account is as it was: its own password still logs in, the other does not
    assert user_of(login(client, EMAIL)) == user_id
    assert (login(client, EMAIL, OTHER_PASSWORD).status_code) == 401


@pytest.mark.parametrize("email", [EMAIL, EMAIL.upper()])
def test_signing_up_never_gives_an_existing_account_a_password(client, test_engine, email):
    # an account made before sign-up existed, without a password
    create_user(test_engine, email=EMAIL)

    response = register(client, email)

    assert (response.status_code, response.json()) == (409, ACCOUNT_EXISTS)
    assert stored_users(test_engine) == [(EMAIL, False)]
    assert (login(client, EMAIL).status_code, login(client, EMAIL).json()) == (401, REFUSED_LOGIN)


@pytest.mark.parametrize(
    "body",
    [
        {"email": EMAIL, "password": "short"},
        {"email": "not-an-email", "password": PASSWORD},
        {"email": EMAIL},
        {"password": PASSWORD},
        {"email": EMAIL, "password": PASSWORD, "user_id": 1},
        {},
    ],
)
def test_an_invalid_sign_up_is_422_and_never_echoes_the_password(client, test_engine, body):
    response = client.post("/auth/register", json=body)

    assert response.status_code == 422
    assert PASSWORD not in response.text
    assert stored_users(test_engine) == []


# --- logging in with the email ---


@pytest.mark.parametrize("email", [EMAIL.upper(), "Asha.Rao@Example.com", f"  {EMAIL}  "])
def test_login_matches_the_email_whatever_its_case_and_spaces(client, email):
    user_id = user_of(register(client, EMAIL))

    assert user_of(login(client, email)) == user_id


@pytest.mark.parametrize(
    ("email", "password"),
    [(EMAIL.upper(), OTHER_PASSWORD), ("asha.rao@example.org", PASSWORD)],
)
def test_a_refused_login_says_nothing_about_the_email(client, email, password):
    register(client, EMAIL)

    response = login(client, email, password)

    assert (response.status_code, response.json()) == (401, REFUSED_LOGIN)


def test_accounts_differing_only_in_case_are_kept_apart(client, test_engine, service_session):
    # two accounts made before emails were normalized
    lower = create_user(test_engine, email=EMAIL)
    upper = create_user(test_engine, email=EMAIL.upper())
    auth = AuthService(service_session)
    auth.set_password(lower, PASSWORD)
    auth.set_password(upper, OTHER_PASSWORD)

    # each logs in with its own email, exactly as stored
    assert user_of(login(client, EMAIL, PASSWORD)) == lower
    assert user_of(login(client, EMAIL.upper(), OTHER_PASSWORD)) == upper
    # another case names neither of them, so no login picks one
    for password in (PASSWORD, OTHER_PASSWORD):
        response = login(client, "Asha.Rao@Example.com", password)
        assert (response.status_code, response.json()) == (401, REFUSED_LOGIN)
    # and the email is taken, in any case: nothing is merged or deleted
    assert register(client, "ASHA.rao@example.com").status_code == 409
    with Session(test_engine) as session:
        assert session.scalar(select(func.count()).select_from(User)) == 2
