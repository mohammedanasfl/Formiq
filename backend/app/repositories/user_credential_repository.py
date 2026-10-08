from sqlalchemy.orm import Session

from app.models import UserCredential


class UserCredentialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, credential: UserCredential) -> UserCredential:
        self.session.add(credential)
        self.session.flush()
        return credential

    def get_by_user_id(self, user_id: int) -> UserCredential | None:
        return self.session.get(UserCredential, user_id)
