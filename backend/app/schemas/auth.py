from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

MIN_PASSWORD_LENGTH = 8
# Argon2 hashes any length; the limit only bounds the work one request asks for.
MAX_PASSWORD_LENGTH = 1024


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: Annotated[str, StringConstraints(min_length=1, max_length=255)]
    # never stripped: a password is exactly what was typed
    password: Annotated[str, StringConstraints(min_length=1, max_length=MAX_PASSWORD_LENGTH)]


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"


class RegisterRequest(BaseModel):
    """A new account: the email it signs in with, and its password. Nothing
    else, so the client never names a user id."""

    model_config = ConfigDict(extra="forbid")

    # stored in lower case, without surrounding spaces; an address is one account
    # whatever its case, and login matches it so (app.core.emails)
    email: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$"
        ),
    ]
    # never stripped: a password is exactly what was typed
    password: Annotated[
        str, StringConstraints(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    ]
