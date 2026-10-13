from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, user: User) -> User:
        self.session.add(user)
        self.session.flush()
        return user

    def get_by_id(self, user_id: int) -> User | None:
        return self.session.get(User, user_id)

    def get_by_id_for_update(self, user_id: int) -> User | None:
        """The user, with their row locked until the transaction ends, so that
        changes checked against the user's other rows run one at a time for
        each user. FOR NO KEY UPDATE: rows referencing the user can still be
        inserted meanwhile."""
        return self.session.scalars(
            select(User).where(User.id == user_id).with_for_update(key_share=True)
        ).one_or_none()

    def get_by_email(self, email: str) -> User | None:
        return self.session.execute(
            select(User).where(User.email == email)
        ).scalar_one_or_none()

    def get_by_phone(self, phone: str) -> User | None:
        return self.session.execute(
            select(User).where(User.phone == phone)
        ).scalar_one_or_none()

    def delete(self, user: User) -> None:
        self.session.delete(user)
        self.session.flush()
