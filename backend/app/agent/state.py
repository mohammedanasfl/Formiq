import operator
from collections.abc import Sequence
from typing import Annotated, TypedDict

from app.agent.context import (
    ConversationContext,
    ConversationTurn,
    compact_conversation,
)
from app.agent.policy import CoachDecision
from app.ai import CoachMessage


class CoachState(TypedDict):
    """The execution state of one coach turn: plain data, nothing else.

    A turn starts from initial_state(), which sets every field. The state holds
    no runtime dependencies (sessions, services, the provider) and no trusted
    identity: those are in CoachContext, which no node can change.

    It is not memory. Each request starts a new state that is dropped after the
    reply, and Formiq data is not copied in ahead of time: the model reads what
    it needs with tools, and their results, bounded by the tools' limits, are
    the only Formiq data in it.
    """

    # the user's request, unchanged during the turn
    user_message: str
    # The earlier conversation the client sent, compacted to its bound
    # (app.agent.context) before the turn starts: context, not Formiq data.
    conversation: ConversationContext
    # What followed it, in order: the model's turns and the tool results. Nodes
    # only append. Bounded by the tool loop: at most max_tool_iterations + 1
    # model turns, each followed by one result per tool call (except the
    # accepted respond call that ends the turn), and a turn with more than
    # MAX_REQUESTED_TOOL_CALLS_PER_TURN calls is rejected.
    messages: Annotated[list[CoachMessage], operator.add]
    # rounds of tool calls run so far
    iteration_count: int
    # model requests whose context had to be compacted to fit the budget
    # (at most MAX_CONTEXT_COMPACTIONS)
    context_compactions: int
    # the reply to the user, which ends the turn; None until then
    final_response: str | None
    # the intent and decision the turn ended with, checked against the policy
    # (app.agent.policy); None until then. Never the model's reasoning.
    decision: CoachDecision | None


def initial_state(
    user_message: str, conversation: Sequence[ConversationTurn] = ()
) -> CoachState:
    """The state a turn starts from: the user's message and the bounded earlier
    conversation, and nothing else yet."""
    return {
        "user_message": user_message,
        "conversation": compact_conversation(conversation),
        "messages": [],
        "iteration_count": 0,
        "context_compactions": 0,
        "final_response": None,
        "decision": None,
    }
