"""Passwords and access tokens: the only code that hashes a password or signs a
token. Nothing here reads the database or logs what it is given.

Passwords are hashed with Argon2id (argon2-cffi's defaults, RFC 9106's low
memory profile). An access token is a JWT signed with AUTH_JWT_SECRET whose
subject is the user's id: the one source of the user a request acts for.
"""

import re
from datetime import UTC, datetime, timedelta
from functools import cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import MIN_JWT_SECRET_LENGTH
from app.schemas.workout_plan import MAX_INTEGER

_hasher = PasswordHasher()

# a user id as a token carries it: a positive integer, written one way only
_SUBJECT = re.compile(r"[1-9][0-9]*")


class InvalidTokenError(Exception):
    """The access token is missing a claim, malformed, wrongly signed or expired."""


class AuthNotConfiguredError(Exception):
    """AUTH_JWT_SECRET is not set, so no token can be issued or verified."""


def hash_password(password: str) -> str:
    """The password's Argon2id hash, with its own random salt."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Whether the password is the one the hash was made from."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@cache
def _unused_hash() -> str:
    return hash_password("formiq: no user has this password")


def verify_no_password(password: str) -> None:
    """Spends the time a verification takes, for a login with no credential to
    check, so its answer takes as long as a wrong password's."""
    verify_password(password, _unused_hash())


class AccessTokens:
    """Issues and verifies access tokens with one secret and algorithm."""

    def __init__(self, secret: str, algorithm: str = "HS256", expire_minutes: int = 30) -> None:
        if algorithm not in MIN_JWT_SECRET_LENGTH:
            raise ValueError("only HMAC algorithms are supported")
        if len(secret) < MIN_JWT_SECRET_LENGTH[algorithm]:
            raise ValueError(
                f"the signing secret must be at least {MIN_JWT_SECRET_LENGTH[algorithm]} characters"
            )
        self._secret = secret
        self._algorithm = algorithm
        self.expire_minutes = expire_minutes

    def __repr__(self) -> str:
        return f"AccessTokens(algorithm={self._algorithm!r}, expire_minutes={self.expire_minutes})"

    def issue(self, user_id: int, *, now: datetime | None = None) -> str:
        """A token for the user, valid for expire_minutes from now."""
        is_id = isinstance(user_id, int) and not isinstance(user_id, bool)
        if not is_id or not 1 <= user_id <= MAX_INTEGER:
            raise ValueError("a token is issued for a user id")
        issued_at = now or datetime.now(UTC)
        claims = {
            "sub": str(user_id),
            "iat": issued_at,
            "exp": issued_at + timedelta(minutes=self.expire_minutes),
        }
        return jwt.encode(claims, self._secret, algorithm=self._algorithm)

    def verify(self, token: str) -> int:
        """The id of the user the token was issued for.

        Raises InvalidTokenError for a token that is malformed, signed with
        another secret or algorithm, expired, issued in the future, or without
        a canonical user id as its subject.
        """
        try:
            claims = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "iat", "exp"]},
            )
        except jwt.PyJWTError as error:
            raise InvalidTokenError("the access token is not valid") from error
        subject = claims["sub"]
        if not isinstance(subject, str) or not _SUBJECT.fullmatch(subject):
            raise InvalidTokenError("the access token is not valid")
        user_id = int(subject)
        if user_id > MAX_INTEGER:
            raise InvalidTokenError("the access token is not valid")
        return user_id
