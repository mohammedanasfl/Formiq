import logging
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.agent import (
    CoachContext,
    PendingProposal,
    CoachDecision,
    ConversationTurn,
    Decision,
    EquipmentSaid,
    SafetyCategory,
    coach_graph,
    initial_state,
)
from app.agent.policy import ANSWERS
from app.ai import GeminiProvider
from app.approvals import ProposalTerms, WriteProposal
from app.observability import TRACING_OFF, Failure, RunTrace, Tracer, classify
from app.observability.trajectory import (
    PROPOSAL_CREATED,
    PROPOSAL_DISCARDED,
    PROPOSAL_NOT_ATTEMPTED,
    PROPOSAL_NOT_CREATED,
    PROPOSAL_SHOWN_PENDING,
)
from app.repositories import UserRepository
from app.services.exceptions import UserNotFoundError
from app.services.exercise_catalog_service import ExerciseCatalogService
from app.services.plan_proposal_service import PlanProposalService
from app.services.user_profile_service import UserProfileService
from app.services.user_service import UserService
from app.services.workout_plan_service import WorkoutPlanService
from app.services.workout_session_service import WorkoutSessionService
from app.tools import FormiqTools
from app.tools.equipment import StatedEquipment, equipment_key, stated_equipment
from app.tools.schemas import ProposedWorkoutPlanOutput

logger = logging.getLogger(__name__)

# the decisions that answer the user, and so may show them a proposed plan
_ANSWERS = ANSWERS


@dataclass(frozen=True)
class CoachAnswer:
    reply: str
    # The workout plan the coach proposed in this turn, for the user to review
    # and approve, and how it was described, when the turn ended with an
    # answer; or else the one awaiting their approval, when the turn read it
    # (get_pending_proposal), as it is kept. Not a saved plan.
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
                    # recorded once it is kept: the outcome is Formiq's state, not the model's word
                    coverage = proposal[1].coverage
                    trace.trajectory.proposal(
                        PROPOSAL_CREATED,
                        proposal_ref=proposal[0].proposal_id[:8],
                        complete=None if coverage is None else coverage.complete,
                        missing_regions=[] if coverage is None else list(coverage.missing_regions),
                    )
                elif answered and tools.pending_shown is not None:
                    # the proposal awaiting their approval, which the turn read
                    # again: shown again as it is kept, with its own binding
                    proposal = tools.pending_shown
                    trace.trajectory.proposal(PROPOSAL_SHOWN_PENDING)
                elif tools.proposals:
                    # Formiq accepted one, but the turn did not end with an answer
                    trace.trajectory.proposal(PROPOSAL_DISCARDED)
            except Exception as error:
                failure = (
                    Failure.USER_NOT_FOUND
                    if isinstance(error, UserNotFoundError)
                    else classify(error)
                )
                self._finish_trajectory(trace, failure)
                trace.finish(failure, **trace.trajectory.metadata())
                logger.info("Coach request %s ended: status=%s", request_id, failure)
                raise
            status = outcome_status(decision)
            self._finish_trajectory(
                trace, status, intent=str(decision.intent), decision=str(decision.decision)
            )
            trace.finish(
                status,
                **trace.trajectory.metadata(),
                intent=decision.intent,
                decision=decision.decision,
                safety_category=decision.safety,
                tools_used=list(decision.tools_used),
                reply_chars=len(reply),
            )
            trace.content(output={"role": "assistant", "content": reply})
            logger.info("Coach request %s ended: status=%s", request_id, status)
            return CoachAnswer(reply, proposal)

    @staticmethod
    def _finish_trajectory(trace: RunTrace, status: str, **fields: str) -> None:
        """The turn's trajectory ends (app.observability.trajectory): a proposal
        tried and not kept is recorded as not created, the status and what the
        turn ended with are set, and the summary goes to the log. The trace gets
        its aggregates from it."""
        journal = trace.trajectory
        if journal.proposal_outcome == PROPOSAL_NOT_ATTEMPTED and journal.proposal_attempts:
            journal.proposal(PROPOSAL_NOT_CREATED)
        journal.finish(status, **fields)
        journal.log_summary()

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
        # earlier awaits the user's approval, so the reply may point them to it,
        # and the model is told to read it before saying anything about it
        waiting = (
            []
            if self.proposal_terms is None
            else PlanProposalService(self.session, self.proposal_terms).awaiting_approval(user_id)
        )
        pending = None
        if waiting:
            left = waiting[0].expires_at - self.proposal_terms.clock()
            pending = PendingProposal(
                expires_in_minutes=max(1, math.ceil(left.total_seconds() / 60)),
                revises_plan_id=waiting[0].parameters.get("replaces_plan_id"),
            )
        # What the user said about their equipment in any turn of theirs, not
        # only the turns the model is sent: one reading, for the model's note
        # and for the tools' filtering, so that a limit they stated is kept
        # however long ago they said it.
        stated, said = read_equipment(
            history,
            message,
            [item.name for item in ExerciseCatalogService(self.session).list_equipment(is_active=True)],
        )
        # End the read transaction, so its connection goes back to the pool
        # while the model answers, which can take seconds. The tools end theirs
        # the same way.
        self.session.rollback()

        # The user goes into the run's context, never into the state: the model
        # cannot choose or change whose data the tools read.
        state = initial_state(message, history, said)
        # The conversation the model sees, the user's message last: what the
        # user said there (which plan they mean) holds for the tools, and so
        # does the equipment they said anywhere in the conversation (stated).
        # Context, never authority: identity, ownership and the approval stay
        # with Formiq.
        tools = self._tools(
            [*((turn.role, turn.text) for turn in state["conversation"].turns), ("user", message)],
            stated,
        )
        state = coach_graph.invoke(
            state,
            context=CoachContext(
                user_id=user_id,
                provider=self.provider,
                tools=tools,
                trace=trace,
                proposal_awaiting_approval=bool(waiting),
                pending_proposal=pending,
            ),
        )
        trace.update(iterations=state["iteration_count"], compactions=state["context_compactions"])
        return state["final_response"], state["decision"], tools

    def _tools(
        self, conversation: Sequence[tuple[str, str]], stated: StatedEquipment | None = None
    ) -> FormiqTools:
        """The coach's tools, reading through the services on this session, and
        proposing plans on the proposal terms, in this conversation, with the
        equipment the user said they have and lack in all of it."""
        return FormiqTools(
            users=UserService(self.session),
            profiles=UserProfileService(self.session),
            plans=WorkoutPlanService(self.session),
            sessions=WorkoutSessionService(self.session),
            catalog=ExerciseCatalogService(self.session),
            end_read=self.session.rollback,
            proposal_terms=self.proposal_terms,
            pending_proposals=(
                None
                if self.proposal_terms is None
                else PlanProposalService(self.session, self.proposal_terms)
            ),
            conversation=conversation,
            stated=stated,
        )


def read_equipment(
    history: Sequence[ConversationTurn], message: str, catalog_names: Sequence[str]
) -> tuple[StatedEquipment, EquipmentSaid]:
    """What the user said about the equipment they have and lack, in every user
    turn the client sent and in this message, oldest first so that a later
    statement replaces an earlier one (app.tools.equipment), and the same as the
    note for the model (EquipmentSaid, by the catalog's names). Only the user's
    own turns are read: a turn from "coach" is the client's claim of what the
    coach said, and says nothing of what the user has."""
    names = {equipment_key(name): name for name in catalog_names}
    words = [turn.text for turn in history if turn.role == "user"]
    stated = stated_equipment([*words, message], list(names))

    def named(keys: frozenset[str]) -> tuple[str, ...]:
        return tuple(name for key, name in names.items() if key in keys)

    return stated, EquipmentSaid(
        has=named(stated.has), lacks=named(stated.lacks), only_these=stated.has_nothing_else
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
