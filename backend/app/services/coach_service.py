from sqlalchemy.orm import Session

from app.agent import CoachContext, coach_graph, initial_state
from app.ai import GeminiProvider
from app.repositories import UserRepository
from app.services.exceptions import UserNotFoundError
from app.services.exercise_catalog_service import ExerciseCatalogService
from app.services.user_profile_service import UserProfileService
from app.services.user_service import UserService
from app.services.workout_plan_service import WorkoutPlanService
from app.services.workout_session_service import WorkoutSessionService
from app.tools import FormiqTools


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
        # End the read transaction, so its connection goes back to the pool
        # while the model answers, which can take seconds. The tools end theirs
        # the same way.
        self.session.rollback()

        # The user goes into the run's context, never into the state: the model
        # cannot choose or change whose data the tools read.
        state = coach_graph.invoke(
            initial_state(message),
            context=CoachContext(user_id=user_id, provider=self.provider, tools=self._tools()),
        )
        return state["final_response"]

    def _tools(self) -> FormiqTools:
        """The coach's read-only tools, reading through the services on this session."""
        return FormiqTools(
            users=UserService(self.session),
            profiles=UserProfileService(self.session),
            plans=WorkoutPlanService(self.session),
            sessions=WorkoutSessionService(self.session),
            catalog=ExerciseCatalogService(self.session),
            end_read=self.session.rollback,
        )
