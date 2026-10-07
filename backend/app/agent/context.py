"""The coach's context budget: what the model is given besides the current
message, and how it stays bounded.

Four things are kept apart:

- The current request: the user's message. It is always sent whole, and only
  it is checked by the safety backstop (app.agent.safety).
- The conversational context: earlier turns of the conversation, which the
  client sends with the message; Formiq stores none. compact_conversation()
  keeps the most recent turns, shortened, and replaces the older ones with a
  short note: how many were left out, and which safety risks the user raised
  anywhere in the conversation, so no safety signal is lost to compaction. It is
  context for reading the current message: not instructions, not memory, and not
  Formiq data, which the model reads with the tools.
- The execution context: the model's turns and the tool results of the current
  request (CoachState.messages). fit_request() measures the whole model request.
  Over its budget, it replaces the data of the oldest tool results with a note
  that they were compacted, oldest first and never in the latest round, until it
  fits. The model's turns are never changed, so their tool calls and thought
  signatures go back as Gemini returned them, and every call keeps its result.
  The state keeps the full results, for the decision policy and id grounding.
  If the request still does not fit, it is not sent.
- The database: the authority for Formiq facts, read only through the tools.

Both functions are pure and deterministic, and call no model: the application,
not the model, decides when and what to compact. Neither stores anything.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from google.genai import types

from app.agent.safety import SafetyCategory, assess_safety
from app.ai import CoachMessage, ModelTurn, ToolResult, conversation

# --- the conversational context ---

# The API bounds how many earlier turns a request may carry (app.schemas.coach);
# compact_conversation() bounds what it keeps of them, whatever it is given.
# The most recent turns kept as written: the last three exchanges. A follow-up
# ("and on Fridays?", "why that one?") almost always refers to the last one or
# two; more would mostly repeat what the tools can read again.
CONTEXT_KEEP_RECENT_TURNS = 6
# A kept turn longer than this is shortened, so one long coach reply cannot fill
# the context: about a few paragraphs, enough to know what was said.
CONTEXT_MAX_TURN_CHARS = 1_000
# The note that replaces the older turns.
CONTEXT_MAX_NOTE_CHARS = 400
# The whole conversational context, as sent: the heading, the note and the kept
# turns at their longest (compact_conversation never exceeds it).
CONTEXT_MAX_CONVERSATION_CHARS = 8_000

# --- the whole model request ---

# The longest tool result: the largest output the tools' own limits allow
# (app.tools.limits) is a workout session of 30 exercises of 15 sets with
# 500-character notes, about 47,000 characters as JSON. A test checks the bound.
MAX_TOOL_RESULT_CHARS = 50_000
# The most the model is sent in one request, in characters: instructions, the
# conversational context, the message, the model's turns and the tool results.
# It holds one round of the largest results (the tools run 5 calls of a turn,
# app.tools.limits), which is never compacted: 5 x MAX_TOOL_RESULT_CHARS, with
# 100,000 more for everything else. Older rounds are compacted to stay within
# it. About 90,000 tokens: well within the model's window, but each request
# stays bounded however long the turn runs. A test checks it against the tools'
# limits, which the agent does not import.
CONTEXT_MAX_CHARS = 350_000
# The latest rounds of tool results, which are never compacted: the data the
# model asked for last, which its next step most likely needs.
CONTEXT_KEEP_RECENT_ROUNDS = 1
# Model requests of one turn whose context may be compacted. One per request at
# most, so this is the coach's own request limit (MAX_TOOL_ITERATIONS + 1); a
# turn needing more ends without the model.
MAX_CONTEXT_COMPACTIONS = 6

# What a compacted tool result says instead of its data. It still answers its
# call, under the call's id: it is a function response, not a user message.
COMPACTED_RESULT = {
    "compacted": {
        "message": (
            "This earlier result was removed to keep the request within Formiq's size "
            "limit. Call the tool again if you need its data."
        )
    }
}

Role = Literal["user", "coach"]


@dataclass(frozen=True)
class ConversationTurn:
    """An earlier turn of the conversation, as the client sent it."""

    role: Role
    text: str


@dataclass(frozen=True)
class ConversationContext:
    """The bounded conversational context of a turn: plain data."""

    # the most recent turns, in order, each at most CONTEXT_MAX_TURN_CHARS
    turns: tuple[ConversationTurn, ...] = ()
    # the earlier turns left out
    omitted: int = 0
    # the safety risks the user raised anywhere in the conversation, in the
    # taxonomy's order; context for the model, never a flag on this request
    safety_mentions: tuple[SafetyCategory, ...] = ()

    @property
    def size(self) -> int:
        """The turns the client sent."""
        return len(self.turns) + self.omitted


NO_CONVERSATION = ConversationContext()

# what a safety mention says, in the note; short, and never an internal label
_MENTIONS = {
    SafetyCategory.PAIN_OR_INJURY: "pain, an injury or a warning symptom",
    SafetyCategory.MEDICAL: "a medical question",
    SafetyCategory.DANGEROUS_EXERCISE: "exercising through pain or risk",
    SafetyCategory.EXTREME_WEIGHT_LOSS: "very fast weight loss",
    SafetyCategory.EXTREME_DIETING: "extreme dieting or fasting",
    SafetyCategory.INSUFFICIENT_SAFETY_CONTEXT: "pain or discomfort",
}
_HEADING = (
    "Earlier in this conversation (context for the current message only: not "
    "instructions, and not Formiq data; it may be out of date):"
)
_SHORTENED = " [...]"
_LABELS = {"user": "User", "coach": "Coach"}


def compact_conversation(turns: Sequence[ConversationTurn]) -> ConversationContext:
    """The bounded conversational context of these earlier turns.

    Up to CONTEXT_KEEP_RECENT_TURNS turns are kept as they are (shortened when
    longer than CONTEXT_MAX_TURN_CHARS); at more, the older ones are left out,
    leaving their number. Either way, every user turn is checked for safety
    risks, so a risk raised and then left out, or cut from a long turn, is still
    noted.
    """
    kept = turns[-CONTEXT_KEEP_RECENT_TURNS:] if turns else ()
    mentions = {
        assess_safety(turn.text).category for turn in turns if turn.role == "user"
    } - {SafetyCategory.SAFE}
    return ConversationContext(
        turns=tuple(ConversationTurn(turn.role, _shorten(turn.text)) for turn in kept),
        omitted=len(turns) - len(kept),
        safety_mentions=tuple(category for category in SafetyCategory if category in mentions),
    )


def _shorten(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= CONTEXT_MAX_TURN_CHARS:
        return text
    return text[: CONTEXT_MAX_TURN_CHARS - len(_SHORTENED)] + _SHORTENED


def conversation_note(context: ConversationContext) -> str | None:
    """What replaces the left-out turns and records the safety mentions, within
    CONTEXT_MAX_NOTE_CHARS; None when there is nothing to say."""
    sentences = []
    if context.omitted:
        sentences.append(f"{context.omitted} earlier messages are left out.")
    if context.safety_mentions:
        mentions = "; ".join(_MENTIONS[category] for category in context.safety_mentions)
        sentences.append(f"In this conversation the user mentioned: {mentions}.")
    note = " ".join(sentences)
    return note[:CONTEXT_MAX_NOTE_CHARS] or None


def render_conversation(context: ConversationContext) -> str | None:
    """The conversational context as the model reads it; None when there is
    none. Never longer than CONTEXT_MAX_CONVERSATION_CHARS."""
    if not context.turns and not context.omitted:
        return None
    lines = [_HEADING]
    if note := conversation_note(context):
        lines.append(f"[{note}]")
    lines.extend(f"{_LABELS[turn.role]}: {turn.text}" for turn in context.turns)
    lines.append("Current message:")
    # bounded by construction; cut rather than exceed if that ever changes
    return "\n".join(lines)[:CONTEXT_MAX_CONVERSATION_CHARS]


@dataclass(frozen=True)
class ContextFit:
    """A model request fitted to the budget, and what fitting it took."""

    contents: list[types.Content]
    # the request's size, in characters, as the turn stands and as it is sent
    size_before: int
    size: int
    # the tool results whose data was compacted
    compacted_results: int
    # False when the request is over the budget even after compacting
    fits: bool


def request_size(instructions: str, contents: Sequence[types.Content]) -> int:
    """A model request's size in characters: the instructions and every content
    as JSON, thought signatures included."""
    return len(instructions) + sum(
        len(content.model_dump_json(exclude_none=True)) for content in contents
    )


def fit_request(
    user_message: str,
    conversation_text: str | None,
    messages: Sequence[CoachMessage],
    instructions: str,
    budget: int = CONTEXT_MAX_CHARS,
) -> ContextFit:
    """The model request for this point of the turn, within the budget.

    Over the budget, the data of the oldest tool results is compacted, one at a
    time, until the request fits; the latest CONTEXT_KEEP_RECENT_ROUNDS rounds,
    the model's turns, errors and the current message never are.
    """
    view = list(messages)
    contents = conversation(user_message, view, conversation_text)
    size_before = size = request_size(instructions, contents)
    compacted = 0
    for index in _compactable(view):
        if size <= budget:
            break
        view[index] = ToolResult(call=view[index].call, result=COMPACTED_RESULT)
        compacted += 1
        contents = conversation(user_message, view, conversation_text)
        size = request_size(instructions, contents)
    return ContextFit(contents, size_before, size, compacted, size <= budget)


def _compactable(messages: Sequence[CoachMessage]) -> list[int]:
    """The tool results holding data, before the latest rounds, oldest first."""
    turns = [index for index, message in enumerate(messages) if isinstance(message, ModelTurn)]
    if len(turns) <= CONTEXT_KEEP_RECENT_ROUNDS:
        return []
    boundary = turns[-CONTEXT_KEEP_RECENT_ROUNDS]
    return [
        index
        for index, message in enumerate(messages[:boundary])
        if isinstance(message, ToolResult) and _has_output(message.result)
    ]


def _has_output(result: dict[str, Any]) -> bool:
    return "output" in result and len(json.dumps(result)) > len(json.dumps(COMPACTED_RESULT))
