from sqlalchemy.orm import Session

from app.core.security import (
    AccessTokens,
    InvalidTokenError,
    hash_password,
    verify_no_password,
    verify_password,
)
from app.models import User, UserCredential
from app.repositories import UserCredentialRepository, UserRepository
from app.schemas.auth import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.services.exceptions import (
    AuthenticationError,
    InvalidCredentialsError,
    InvalidPasswordError,
    InvalidUserError,
    UserNotFoundError,
)


class AuthService:
    """Who a request acts for: a login gives an access token, and the token,
    verified, gives the user. Nothing else chooses the user.

    tokens is needed to log in and to authenticate; setting a password issues
    no token.
    """

    def __init__(self, session: Session, tokens: AccessTokens | None = None) -> None:
        self.session = session
        self.tokens = tokens
        self.users = UserRepository(session)
        self.credentials = UserCredentialRepository(session)

    def login(self, email: str, password: str) -> str:
        """An access token for the user with this email and password.

        Raises InvalidCredentialsError, the same way and after the same work,
        for an unknown email, a user without a password and a wrong password.
        """
        user = self.users.get_by_email(email)
        credential = None if user is None else self.credentials.get_by_user_id(user.id)
        if credential is None:
            verify_no_password(password)
            raise InvalidCredentialsError("invalid email or password")
        if not verify_password(password, credential.password_hash):
            raise InvalidCredentialsError("invalid email or password")
        return self.tokens.issue(user.id)

    def authenticate(self, token: str) -> User:
        """The user the access token was issued for.

        Raises AuthenticationError for a token that does not verify, or whose
        user no longer exists.
        """
        try:
            user_id = self.tokens.verify(token)
        except InvalidTokenError as error:
            raise AuthenticationError("invalid access token") from error
        user = self.users.get_by_id(user_id)
        if user is None:
            raise AuthenticationError("invalid access token")
        return user

    def set_password(self, user_id: int, password: str) -> None:
        """Sets, or replaces, the user's login password. Login is by email, so
        the user must have one."""
        try:
            if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
                raise InvalidPasswordError(
                    f"a password has {MIN_PASSWORD_LENGTH} to {MAX_PASSWORD_LENGTH} characters"
                )
            user = self.users.get_by_id(user_id)
            if user is None:
                raise UserNotFoundError(f"user {user_id} does not exist")
            if user.email is None:
                raise InvalidUserError("the user has no email to log in with")
            credential = self.credentials.get_by_user_id(user_id)
            if credential is None:
                self.credentials.create(
                    UserCredential(user_id=user_id, password_hash=hash_password(password))
                )
            else:
                credential.password_hash = hash_password(password)
                self.session.flush()
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise
