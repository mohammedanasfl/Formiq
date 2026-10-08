"""Passwords and access tokens (app.core.security), and their settings.

No test reads the database: these are the pure parts of authentication. The
secrets here are test-only values.
"""

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.security import (
    AccessTokens,
    InvalidTokenError,
    hash_password,
    verify_no_password,
    verify_password,
)

SECRET = "unit-test-signing-secret-0123456789abcdef"
# long enough for every algorithm, to sign tokens the tests then reject
LONG_SECRET = "unit-test-signing-secret-for-every-algorithm-0123456789abcdef0123"
OTHER_SECRET = "another-unit-test-secret-0123456789abcdef"
PASSWORD = "correct horse battery staple"
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=UTC)
APP = Path(__file__).resolve().parents[2] / "app"


@pytest.fixture
def tokens():
    return AccessTokens(SECRET)


def signed(claims, secret=SECRET, algorithm="HS256"):
    return jwt.encode(claims, secret, algorithm=algorithm)


def claims_for(subject="7", *, issued=None, expires=None, **extra):
    issued = issued or datetime.now(UTC)
    return {"sub": subject, "iat": issued, "exp": expires or issued + timedelta(minutes=5), **extra}


# --- passwords ---


def test_a_password_is_stored_as_a_salted_argon2id_hash():
    first, second = hash_password(PASSWORD), hash_password(PASSWORD)

    assert first.startswith("$argon2id$")
    # a random salt each time, and never the password itself
    assert first != second
    assert PASSWORD not in first and PASSWORD not in second


def test_the_correct_password_verifies():
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


@pytest.mark.parametrize(
    "attempt", ["", "correct horse battery stapl", PASSWORD.upper(), f" {PASSWORD}", f"{PASSWORD} "]
)
def test_any_other_password_fails(attempt):
    assert verify_password(attempt, hash_password(PASSWORD)) is False


@pytest.mark.parametrize("stored", ["", "not a hash", PASSWORD, "$argon2id$v=19$broken"])
def test_a_malformed_stored_hash_fails_instead_of_raising(stored):
    assert verify_password(PASSWORD, stored) is False


def test_a_login_without_a_credential_still_does_the_work_and_returns_nothing():
    assert verify_no_password(PASSWORD) is None


# --- issuing and verifying tokens ---


def test_a_valid_token_gives_the_user_it_was_issued_for(tokens):
    assert tokens.verify(tokens.issue(7)) == 7
    assert tokens.verify(tokens.issue(2_147_483_647)) == 2_147_483_647


def test_a_token_carries_only_the_user_and_its_times(tokens):
    token = tokens.issue(7, now=NOW)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_exp": False})
    assert claims == {
        "sub": "7",
        "iat": int(NOW.timestamp()),
        "exp": int((NOW + timedelta(minutes=30)).timestamp()),
    }
    assert jwt.get_unverified_header(token)["alg"] == "HS256"


@pytest.mark.parametrize("user_id", [0, -1, 2_147_483_648, True, "7", 7.0, None])
def test_a_token_is_issued_only_for_a_user_id(tokens, user_id):
    with pytest.raises(ValueError):
        tokens.issue(user_id)


def test_an_expired_token_is_rejected(tokens):
    token = tokens.issue(7, now=datetime.now(UTC) - timedelta(minutes=31))

    with pytest.raises(InvalidTokenError):
        tokens.verify(token)


def test_a_token_issued_in_the_future_is_rejected(tokens):
    issued = datetime.now(UTC) + timedelta(hours=1)

    with pytest.raises(InvalidTokenError):
        tokens.verify(signed(claims_for(issued=issued)))


@pytest.mark.parametrize(
    "token",
    ["", "abc", "a.b.c", "Bearer x", "eyJhbGciOiJIUzI1NiJ9..", "x" * 5000],
    ids=["empty", "word", "three_parts", "scheme", "no_payload", "long"],
)
def test_a_malformed_token_is_rejected(tokens, token):
    with pytest.raises(InvalidTokenError):
        tokens.verify(token)


def test_a_token_signed_with_another_secret_is_rejected(tokens):
    with pytest.raises(InvalidTokenError):
        tokens.verify(AccessTokens(OTHER_SECRET).issue(7))


def test_a_token_with_a_changed_subject_is_rejected(tokens):
    header, _, signature = tokens.issue(7).split(".")
    _, payload, _ = signed(claims_for("8"), OTHER_SECRET).split(".")

    with pytest.raises(InvalidTokenError):
        tokens.verify(f"{header}.{payload}.{signature}")


@pytest.mark.parametrize("algorithm", ["HS384", "HS512"])
def test_a_token_of_another_algorithm_is_rejected(algorithm):
    tokens = AccessTokens(LONG_SECRET)

    with pytest.raises(InvalidTokenError):
        tokens.verify(signed(claims_for(), LONG_SECRET, algorithm))


def test_an_unsigned_token_is_rejected(tokens):
    unsigned = jwt.encode(claims_for(), None, algorithm="none")

    with pytest.raises(InvalidTokenError):
        tokens.verify(unsigned)


@pytest.mark.parametrize("missing", ["sub", "iat", "exp"])
def test_a_token_missing_a_claim_is_rejected(tokens, missing):
    claims = claims_for()
    del claims[missing]

    with pytest.raises(InvalidTokenError):
        tokens.verify(signed(claims))


@pytest.mark.parametrize(
    "subject",
    ["0", "07", "-1", "+7", " 7", "7 ", "7.0", "1e1", "abc", "", "2147483648", "٧"],
)
def test_a_subject_that_is_not_a_canonical_user_id_is_rejected(tokens, subject):
    with pytest.raises(InvalidTokenError):
        tokens.verify(signed(claims_for(subject)))


@pytest.mark.parametrize("subject", [7, None, ["7"], {"id": 7}, True])
def test_a_subject_that_is_not_text_is_rejected(tokens, subject):
    with pytest.raises(InvalidTokenError):
        tokens.verify(signed(claims_for(subject)))


def test_claims_beyond_the_subject_name_no_other_user(tokens):
    # only sub says who the token is for; any other claim is ignored
    token = signed(claims_for("7", user_id=2, authenticated_user_id=2, role="admin"))

    assert tokens.verify(token) == 7


def test_the_error_never_carries_the_token_or_secret(tokens):
    token = AccessTokens(OTHER_SECRET).issue(7)

    with pytest.raises(InvalidTokenError) as raised:
        tokens.verify(token)

    assert token not in str(raised.value) and SECRET not in str(raised.value)
    assert SECRET not in repr(tokens)


# --- configuration ---


@pytest.mark.parametrize(
    ("algorithm", "length"), [("HS256", 32), ("HS384", 48), ("HS512", 64)]
)
def test_tokens_need_a_secret_as_long_as_the_hash(algorithm, length):
    tokens = AccessTokens("x" * length, algorithm)
    assert tokens.verify(tokens.issue(7)) == 7
    for short in ("", "short", "x" * (length - 1)):
        with pytest.raises(ValueError):
            AccessTokens(short, algorithm)


@pytest.mark.parametrize("algorithm", ["none", "RS256", "ES256"])
def test_tokens_use_hmac_only(algorithm):
    with pytest.raises(ValueError):
        AccessTokens(SECRET, algorithm)


def settings(**values):
    return Settings(_env_file=None, database_url="postgresql+psycopg://x@localhost/x", **values)


def test_the_settings_default_to_no_secret_and_short_lived_hs256_tokens():
    configured = settings()

    assert configured.auth_jwt_secret is None
    assert configured.auth_jwt_algorithm == "HS256"
    assert configured.auth_access_token_expire_minutes == 30


def test_an_empty_secret_setting_is_no_secret():
    assert settings(auth_jwt_secret="").auth_jwt_secret is None


@pytest.mark.parametrize(
    "values",
    [
        {"auth_jwt_secret": "x" * 31},
        {"auth_jwt_secret": "x" * 47, "auth_jwt_algorithm": "HS384"},
        {"auth_jwt_secret": "x" * 63, "auth_jwt_algorithm": "HS512"},
        {"auth_jwt_algorithm": "none"},
        {"auth_jwt_algorithm": "RS256"},
        {"auth_access_token_expire_minutes": 0},
        {"auth_access_token_expire_minutes": 1441},
    ],
    ids=[
        "short_secret",
        "short_hs384",
        "short_hs512",
        "none",
        "rs256",
        "no_lifetime",
        "over_a_day",
    ],
)
def test_unsafe_settings_are_rejected(values):
    with pytest.raises(ValidationError):
        settings(**values)


def test_the_secret_setting_stays_out_of_reprs():
    configured = settings(auth_jwt_secret=SECRET)

    assert SECRET not in repr(configured)
    assert configured.auth_jwt_secret.get_secret_value() == SECRET


# --- who can reach credentials ---


@pytest.mark.parametrize("package", ["agent", "tools", "ai", "observability", "evaluation"])
def test_the_coach_never_imports_credentials_or_token_code(package):
    imported = set()
    for path in (APP / package).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported |= {f"{node.module}.{alias.name}" for alias in node.names}
            elif isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}

    forbidden = (
        "app.core.security",
        "UserCredential",
        "user_credential",
        "AuthService",
        "auth_service",
    )
    assert not [name for name in imported if any(part in name for part in forbidden)]
