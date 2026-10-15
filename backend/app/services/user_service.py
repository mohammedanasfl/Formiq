from sqlalchemy.orm import Session

from app.core.emails import normalize_email
from app.models import User
from app.repositories import UserRepository
from app.schemas import UserCreate
from app.services.exceptions import InvalidUserError, UserAlreadyExistsError


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)

    def create_user(self, user_data: UserCreate) -> User:
        """A user without a password, who cannot log in. No route creates one:
        an account is made by signing up (AuthService.register). The email is
        stored and compared as signing up does (app.core.emails)."""
        email = None if user_data.email is None else normalize_email(user_data.email)
        try:
            if email is None and user_data.phone is None:
                raise InvalidUserError("email or phone is required")
            if email is not None and self.users.list_by_normalized_email(email):
                raise UserAlreadyExistsError("a user with this email already exists")
            if user_data.phone is not None and self.users.get_by_phone(user_data.phone) is not None:
                raise UserAlreadyExistsError("a user with this phone already exists")

            user = self.users.create(User(email=email, phone=user_data.phone))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(user)
        return user

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.users.get_by_id(user_id)
