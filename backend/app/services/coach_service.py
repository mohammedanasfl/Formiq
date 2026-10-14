import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agent import (
    CoachContext,
    CoachDecision,
    ConversationTurn,
    Decision,
    SafetyCategory,
    coach_graph,
    initial_state,
)
from app.ai import GeminiProvider
from app.approvals import ProposalTerms, WriteProposal
from app.observability import TRACING_OFF, Failure, RunTrace, Tracer, classify
from app.repositories import UserRepository
from app.services.exceptions import UserNotFoundError
from app.services.exercise_catalog_service import ExerciseCatalogService
from app.services.plan_proposal_service import PlanProposalService
from app.services.user_profile_service import UserProfileService
from app.services.user_service import UserService
from app.services.workout_plan_service import WorkoutPlanService
from app.services.workout_session_service import WorkoutSessionService
from app.tools import FormiqTools
from app.tools.schemas import ProposedWorkoutPlanOutput

logger = logging.getLogger(__name__)

# the decisions that answer the user, and so may show them a proposed plan
_ANSWERS = frozenset({Decision.ANSWER, Decision.RETRIEVE_THEN_ANSWER})


@dataclass(frozen=True)
class CoachAnswer:
    reply: str
    # The workout plan the coach proposed in this turn, for the user to review
    # and approve, and how it was described: the last one, when the turn ended
    # with an answer. Kept for the user's approval; not a saved plan.
    proposal: tuple[WriteProposal, ProposedWorkoutPlanOutput] | None = None


class CoachService:
    def __init__(
        self,
        session: Session,
        provider: GeminiProvider,
        tracer: Tracer = TRACING_OFF,
        proposal_terms: ProposalTerms | None = None,
    ) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.provider = provider
        self.tracer = tracer
        # when proposals are made and how long they wait; None: none is proposed
        self.proposal_terms = proposal_terms

    def reply(
        self, user_id: int, message: str, history: Sequence[ConversationTurn] = ()
    ) -> str:
        """The coach's reply to the user's message (answer() without the
        proposal)."""
        return self.answer(user_id, message, history).reply

    def answer(
        self, user_id: int, message: str, history: Sequence[ConversationTurn] = ()
    ) -> CoachAnswer:
        """The coach's reply to the user's message, from the coach graph, and the
        workout plan it proposed, if any. history is the earlier conversation the
        client sent, oldest first: the graph sees it compacted to its bound, and
        it is stored nowhere.

        Raises AIProviderNotConfiguredError when no API key is set, and
        AIProviderError when the model cannot answer.

        Each request is traced (app.observability) under a request id generated
        here, which the log line at its end repeats: metadata only, and nothing
        the trace records changes the reply.
        """
        request_id = uuid.uuid4().hex
        with self.tracer.request(
            "coach_request",
            request_id=request_id,
            user_id=user_id,
            conversation_turns=len(history),
        ) as trace:
            trace.content(input=lambda: chat_history(message, history))
            try:
                reply, decision, tools = self._reply(user_id, message, history, trace)
                answered = (
                    decision.decision in _ANSWERS and decision.safety is SafetyCategory.SAFE
                )
                proposal = tools.proposals[-1] if answered and tools.proposals else None
                if proposal is not None:
                    # Kept for the user's approval: only the proposal they are
                    # shown. The coach saves no plan; only their approval does.
                    PlanProposalService(self.session, self.proposal_terms).register(proposal[0])
            except Exception as error:
                failure = (
                    Failure.USER_NOT_FOUND
                    if isinstance(error, UserNotFoundError)
                    else classify(error)
                )
                trace.finish(failure)
                logger.info("Coach request %s ended: status=%s", request_id, failure)
                raise
            status = outcome_status(decision)
            trace.finish(
                status,
                intent=decision.intent,
                decision=decision.decision,
                safety_category=decision.safety,
                tools_used=list(decision.tools_used),
                reply_chars=len(reply),
            )
            trace.content(output={"role": "assistant", "content": reply})
            logger.info("Coach request %s ended: status=%s", request_id, status)
            return CoachAnswer(reply, proposal)

    def _reply(
        self,
        user_id: int,
        message: str,
        history: Sequence[ConversationTurn],
        trace: RunTrace,
    ) -> tuple[str, CoachDecision, FormiqTools]:
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        # From Formiq's records, not the conversation: whether a proposal made
        # earlier awaits the user's approval, so the reply may point them to it
        awaiting_approval = self.proposal_terms is not None and PlanProposalService(
            self.session, self.proposal_terms
        ).awaits_approval(user_id)
        # End the read transaction, so its connection goes back to the pool
        # while the model answers, which can take seconds. The tools end theirs
        # the same way.
        self.session.rollback()

        # The user goes into the run's context, never into the state: the model
        # cannot choose or change whose data the tools read.
        tools = self._tools()
        state = coach_graph.invoke(
            initial_state(message, history),
            context=CoachContext(
                user_id=user_id,
                provider=self.provider,
                tools=tools,
                trace=trace,
                proposal_awaiting_approval=awaiting_approval,
            ),
        )
        trace.update(iterations=state["iteration_count"], compactions=state["context_compactions"])
        return state["final_response"], state["decision"], tools

    def _tools(self) -> FormiqTools:
        """The coach's tools, reading through the services on this session, and
        proposing plans on the proposal terms."""
        return FormiqTools(
            users=UserService(self.session),
            profiles=UserProfileService(self.session),
            plans=WorkoutPlanService(self.session),
            sessions=WorkoutSessionService(self.session),
            catalog=ExerciseCatalogService(self.session),
            end_read=self.session.rollback,
            proposal_terms=self.proposal_terms,
        )


def chat_history(message: str, history: Sequence[ConversationTurn]) -> list[dict[str, str]]:
    """The conversation the client sent, and the user's message, as chat
    messages: for a trace that captures content only."""
    roles = {"user": "user", "coach": "assistant"}
    return [
        *({"role": roles[turn.role], "content": turn.text} for turn in history),
        {"role": "user", "content": message},
    ]


def outcome_status(decision: CoachDecision) -> str:
    """What the request ended with, from its validated decision. A request on the
    safety path is a safety redirect whoever wrote the reply; only an answer or
    a question counts as success."""
    if decision.safety is not SafetyCategory.SAFE or decision.decision is Decision.SAFE_REDIRECT:
        return "safety_redirect"
    if decision.decision is Decision.CANNOT_ANSWER:
        return "cannot_answer"
    if decision.decision is Decision.ASK_CLARIFICATION:
        return "clarification"
    return "success"
