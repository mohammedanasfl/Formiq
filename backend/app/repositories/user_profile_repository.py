from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import UserProfile


class UserProfileRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, profile: UserProfile) -> UserProfile:
        self.session.add(profile)
        self.session.flush()
        return profile

    def get_by_id(self, profile_id: int) -> UserProfile | None:
        return self.session.get(UserProfile, profile_id)

    def get_by_user_id(self, user_id: int) -> UserProfile | None:
        return self.session.execute(
            select(UserProfile).where(UserProfile.user_id == user_id)
        ).scalar_one_or_none()

    def update(self, profile: UserProfile) -> UserProfile:
        self.session.add(profile)
        self.session.flush()
        return profile

    def delete(self, profile: UserProfile) -> None:
        self.session.delete(profile)
        self.session.flush()
