import logging
import math
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.agent import (
    CoachContext,
    CoachDates,
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
from app.schemas import WorkoutPlanStatus
from app.services.exceptions import (
    UserNotFoundError,
    WorkoutPlanNotFoundError,
    WorkoutPlanNotRevisableError,
)
from app.services.exercise_catalog_service import ExerciseCatalogService
from app.services.plan_proposal_service import PlanProposalService
from app.services.user_profile_service import UserProfileService
from app.services.user_service import UserService
from app.services.workout_plan_service import WorkoutPlanService
from app.services.workout_session_service import WorkoutSessionService
from app.tools import FormiqTools
from app.tools.coach_calendar import calendar_at
from app.tools.equipment import StatedEquipment, equipment_key, saved_equipment, stated_equipment
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
        self,
        user_id: int,
        message: str,
        history: Sequence[ConversationTurn] = (),
        workout_plan_id: int | None = None,
        timezone: str | None = None,
    ) -> CoachAnswer:
        """The coach's reply to the user's message, from the coach graph, and the
        workout plan it proposed, if any. history is the earlier conversation the
        client sent, oldest first: the graph sees it compacted to its bound, and
        it is stored nowhere.

        workout_plan_id is the saved plan the user opened the coach to change.
        It is checked before anything else runs (so before any model request):
        it must be the user's own and PLANNED, else WorkoutPlanNotFoundError
        (another user's plan is not told apart from a missing one) or
        WorkoutPlanNotRevisableError. The coach is then held to it: a proposal
        of this request revises that plan, or is refused.

        timezone is the user's IANA time zone, from the app (the request schema
        validated it): "today", "tomorrow" and every date the coach reads, shows
        or is held to are the user's local ones in it (Phase 2.7,
        app.tools.coach_calendar). Without it they are UTC dates, which the coach
        is told.

        Raises AIProviderNotConfiguredError when no API key is set, and
        AIProviderError when the model cannot answer.

        Each request is traced (app.observability) under a request id generated
        here, which the log line at its end repeats: metadata only, and nothing
        the trace records changes the reply.
        """
        if workout_plan_id is not None:
            self._check_target(user_id, workout_plan_id)
        request_id = uuid.uuid4().hex
        with self.tracer.request(
            "coach_request",
            request_id=request_id,
            user_id=user_id,
            conversation_turns=len(history),
        ) as trace:
            trace.content(input=lambda: chat_history(message, history))
            if trace.debug is not None:
                # what the client sent, as roles and sizes: never the text
                trace.debug.user_input(message, [(turn.role, turn.text) for turn in history])
            try:
                reply, decision, tools = self._reply(
                    user_id, message, history, trace, workout_plan_id, timezone
                )
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

    def _check_target(self, user_id: int, plan_id: int) -> None:
        """The plan the request names must be the user's own and PLANNED: a
        request is never answered for a plan it may not change. A rejected
        request is not traced: it never reaches the model."""
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        plan = WorkoutPlanService(self.session).get_plan(user_id, plan_id)
        if plan is None:
            raise WorkoutPlanNotFoundError(f"user {user_id} has no workout plan {plan_id}")
        if plan.status != WorkoutPlanStatus.PLANNED:
            raise WorkoutPlanNotRevisableError(
                f"workout plan {plan_id} is {plan.status}: only a PLANNED workout plan can be "
                "changed with the coach"
            )

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
        if trace.debug is not None:
            trace.debug.summary(journal.summary)

    def _reply(
        self,
        user_id: int,
        message: str,
        history: Sequence[ConversationTurn],
        trace: RunTrace,
        workout_plan_id: int | None = None,
        timezone: str | None = None,
    ) -> tuple[str, CoachDecision, FormiqTools]:
        if self.users.get_by_id(user_id) is None:
            raise UserNotFoundError(f"user {user_id} does not exist")
        # From Formiq's records, not the conversation: whether a proposal made
        # earlier awaits the user's approval (one they could still approve), so
        # the reply may point them to it, and the model is told to read it before
        # saying anything about it. A request about a plan is about that plan's
        # proposals only: another plan's is not pointed to, nor is a new workout.
        proposals = (
            None
            if self.proposal_terms is None
            else PlanProposalService(self.session, self.proposal_terms)
        )
        waiting = (
            [] if proposals is None else proposals.awaiting_approval(user_id, revising=workout_plan_id)
        )
        # The proposals this request does not read (it is about one plan) and the plans an
        # approval saved: facts the reply is held to, so that it never says the user has no
        # proposal waiting while another plan's does, nor that a workout was applied when
        # nothing was approved (app.agent.trust.Lifecycle).
        elsewhere = (
            len(proposals.awaiting_approval(user_id)) - len(waiting)
            if proposals is not None and workout_plan_id is not None
            else 0
        )
        approved = frozenset() if proposals is None else proposals.approved_plan_ids(user_id)
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
        # however long ago they said it. It starts from the equipment saved in their
        # profile, which is what they have until they say otherwise in the conversation.
        saved = UserProfileService(self.session).get_saved_equipment(user_id)
        stated, said = read_equipment(
            history,
            message,
            [item.name for item in ExerciseCatalogService(self.session).list_equipment(is_active=True)],
            None if saved is None else saved_equipment(saved.names, saved.none),
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
            workout_plan_id,
            timezone,
        )
        # the one calendar the tools work in, told to the model (a stand-in for the tools may have none)
        calendar = getattr(tools, "calendar", None)
        state = coach_graph.invoke(
            state,
            context=CoachContext(
                user_id=user_id,
                provider=self.provider,
                tools=tools,
                trace=trace,
                proposal_awaiting_approval=bool(waiting),
                pending_proposal=pending,
                target_plan_id=workout_plan_id,
                other_proposals_awaiting=elsewhere,
                approved_plan_ids=approved,
                dates=None
                if calendar is None
                else CoachDates(
                    today=calendar.today,
                    timezone=calendar.timezone,
                    from_request=calendar.source == "request",
                ),
            ),
        )
        trace.update(iterations=state["iteration_count"], compactions=state["context_compactions"])
        return state["final_response"], state["decision"], tools

    def _tools(
        self,
        conversation: Sequence[tuple[str, str]],
        stated: StatedEquipment | None = None,
        target_plan_id: int | None = None,
        timezone: str | None = None,
    ) -> FormiqTools:
        """The coach's tools, reading through the services on this session, and
        proposing plans on the proposal terms, in this conversation, with the
        equipment the user said they have and lack in all of it, and the plan
        the request names (target_plan_id), if any. Their dates are the user's
        local ones in the time zone given, from Formiq's clock, or UTC dates
        without one."""
        now = self.proposal_terms.clock() if self.proposal_terms is not None else datetime.now(UTC)
        calendar = calendar_at(now, timezone)
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
            target_plan_id=target_plan_id,
            # Use the same captured instant for UTC fallback and supplied local zones. Passing the
            # date explicitly prevents FormiqTools from taking a second wall-clock reading.
            today=calendar.today,
            timezone=timezone,
        )


def read_equipment(
    history: Sequence[ConversationTurn],
    message: str,
    catalog_names: Sequence[str],
    saved: StatedEquipment | None = None,
) -> tuple[StatedEquipment, EquipmentSaid]:
    """What the user said about the equipment they have and lack, in every user
    turn the client sent and in this message, oldest first so that a later
    statement replaces an earlier one (app.tools.equipment), and the same as the
    note for the model (EquipmentSaid, by the catalog's names). Only the user's
    own turns are read: a turn from "coach" is the client's claim of what the
    coach said, and says nothing of what the user has. saved is what their
    profile says they have (saved_equipment()): where they stand until a turn of
    theirs says otherwise."""
    names = {equipment_key(name): name for name in catalog_names}
    words = [turn.text for turn in history if turn.role == "user"]
    stated = stated_equipment([*words, message], list(names), saved)

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
