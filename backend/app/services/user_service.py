from sqlalchemy.orm import Session

from app.models import User
from app.repositories import UserRepository
from app.schemas import UserCreate
from app.services.exceptions import InvalidUserError, UserAlreadyExistsError


class UserService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.users = UserRepository(session)

    def create_user(self, user_data: UserCreate) -> User:
        try:
            if user_data.email is None and user_data.phone is None:
                raise InvalidUserError("email or phone is required")
            if user_data.email is not None and self.users.get_by_email(user_data.email) is not None:
                raise UserAlreadyExistsError("a user with this email already exists")
            if user_data.phone is not None and self.users.get_by_phone(user_data.phone) is not None:
                raise UserAlreadyExistsError("a user with this phone already exists")

            user = self.users.create(User(email=user_data.email, phone=user_data.phone))
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        self.session.refresh(user)
        return user

    def get_user_by_id(self, user_id: int) -> User | None:
        return self.users.get_by_id(user_id)
