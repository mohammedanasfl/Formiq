from sqlalchemy.orm import Session

from app.agent import CoachContext, coach_graph
from app.ai import GeminiProvider
from app.repositories import UserRepository
from app.services.exceptions import UserNotFoundError


class CoachService:
    def __init__(self, session: Session, provider: GeminiProvider) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.provider = provider

    def reply(self, user_id: int, message: str) -> str:
        """The coach's reply to the user's message, from the coach graph.

        Raises AIProviderNotConfiguredError when no API key is set, and
        AIProviderError when the model cannot answer.
        """
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        # Nothing else is read: end the read transaction, so its connection goes
        # back to the pool while the model answers, which can take seconds.
        self.session.rollback()

        state = coach_graph.invoke(
            {"user_id": user_id, "message": message},
            context=CoachContext(provider=self.provider),
        )
        return state["reply"]
