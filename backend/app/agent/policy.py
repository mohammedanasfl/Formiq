"""The coach's decision policy: what kind of request the user made, which Formiq
data its answer needs, and which decisions may end the turn.

The model ends every turn with a respond call that names the request's intent,
its decision and the reply. This module checks that decision against what the
turn actually retrieved. It is pure and deterministic: it sees the declared
intent and decision and the tool results, never the model's reasoning, and
stores nothing.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.ai import ToolCall, ToolDeclaration, ToolResult


class Intent(StrEnum):
    GENERAL_FITNESS = "GENERAL_FITNESS"
    PROFILE = "PROFILE"
    WORKOUT_PLAN = "WORKOUT_PLAN"
    WORKOUT_HISTORY = "WORKOUT_HISTORY"
    EXERCISE = "EXERCISE"
    ADAPTATION = "ADAPTATION"
    SAFETY_SENSITIVE = "SAFETY_SENSITIVE"
    AMBIGUOUS = "AMBIGUOUS"


class Decision(StrEnum):
    # from general knowledge: the answer does not depend on the user's Formiq data
    ANSWER = "ANSWER"
    # from Formiq data that tools returned in this turn
    RETRIEVE_THEN_ANSWER = "RETRIEVE_THEN_ANSWER"
    ASK_CLARIFICATION = "ASK_CLARIFICATION"
    SAFE_REDIRECT = "SAFE_REDIRECT"
    CANNOT_ANSWER = "CANNOT_ANSWER"


class DataStatus(StrEnum):
    """What a tool result gives an answer to rely on."""

    AVAILABLE = "AVAILABLE"
    # data, but some of it was left out by the tool's limits (truncated)
    INCOMPLETE = "INCOMPLETE"
    # the user, profile or resource does not exist for this user
    MISSING = "MISSING"
    # the tool failed or rejected the call
    FAILED = "FAILED"
    # neither data nor an error: not something to rely on
    UNEXPECTED = "UNEXPECTED"


@dataclass(frozen=True)
class IntentPolicy:
    # what the intent covers, for the model
    description: str
    # The tools whose data an answer needs: RETRIEVE_THEN_ANSWER requires data
    # from at least one of them, returned in this turn.
    data_tools: frozenset[str]
    decisions: frozenset[Decision]


# ASK_CLARIFICATION, SAFE_REDIRECT and CANNOT_ANSWER answer nothing from data, so
# they suit any request that is not safety-sensitive or ambiguous.
_FALLBACKS = frozenset(
    {Decision.ASK_CLARIFICATION, Decision.SAFE_REDIRECT, Decision.CANNOT_ANSWER}
)
_USER_DATA_TOOLS = frozenset({"get_user_profile", "get_workout_plan", "get_workout_session"})

POLICY: dict[Intent, IntentPolicy] = {
    Intent.GENERAL_FITNESS: IntentPolicy(
        "General training, exercise or nutrition knowledge that does not depend on the "
        "user's own data, such as what progressive overload is.",
        frozenset(),
        frozenset({Decision.ANSWER}) | _FALLBACKS,
    ),
    Intent.PROFILE: IntentPolicy(
        "The user's stored profile: goal, body measurements, experience, training "
        "frequency and location, activity, sleep, diet.",
        frozenset({"get_user_profile"}),
        frozenset({Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
    ),
    Intent.WORKOUT_PLAN: IntentPolicy(
        "One of the user's workout plans: what was prescribed.",
        frozenset({"get_workout_plan"}),
        frozenset({Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
    ),
    Intent.WORKOUT_HISTORY: IntentPolicy(
        "What the user actually did in a workout session: exercises, sets, reps, "
        "weights, effort, including comparing it with the plan.",
        frozenset({"get_workout_session"}),
        frozenset({Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
    ),
    Intent.EXERCISE: IntentPolicy(
        "Facts about exercises, or finding exercises in the Formiq catalog.",
        frozenset({"get_exercise", "search_exercises"}),
        frozenset({Decision.ANSWER, Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
    ),
    Intent.ADAPTATION: IntentPolicy(
        "Changing or tailoring the user's training to their goal, schedule, equipment "
        "or progress.",
        _USER_DATA_TOOLS,
        frozenset({Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
    ),
    Intent.SAFETY_SENSITIVE: IntentPolicy(
        "Pain or injury, medical conditions, diagnosis or treatment, potentially "
        "dangerous exercise, extreme weight loss or dieting, or a recommendation that "
        "would be unsafe with the information available.",
        frozenset(),
        frozenset({Decision.SAFE_REDIRECT}),
    ),
    Intent.AMBIGUOUS: IntentPolicy(
        "A request whose meaning or needed details cannot be determined reliably, such "
        "as 'make it harder' without saying what or how.",
        frozenset(),
        frozenset({Decision.ASK_CLARIFICATION}),
    ),
}

# the tool error codes (app.tools) that mean the data does not exist for this user
MISSING_ERROR_CODES = frozenset({"USER_NOT_FOUND", "PROFILE_NOT_FOUND", "RESOURCE_NOT_FOUND"})

# the model's reply to the user; longer replies are rejected
MAX_REPLY_LENGTH = 8000

RESPOND = ToolDeclaration(
    name="respond",
    description=(
        "End your turn: give the request's intent, your decision and the reply the user "
        "will see. Call it alone, after any data you need has been returned. Formiq "
        "checks the decision against the data retrieved in this turn and tells you if "
        "it cannot be used."
    ),
    parameters={
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [intent.value for intent in Intent],
                "description": "What kind of request the user made.",
            },
            "decision": {
                "type": "string",
                "enum": [decision.value for decision in Decision],
                "description": "How you answer it.",
            },
            "reply": {
                "type": "string",
                "description": "Your reply to the user, and nothing else.",
            },
        },
        "required": ["intent", "decision", "reply"],
    },
)


class Respond(BaseModel):
    """The arguments of a respond call."""

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    decision: Decision
    reply: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_REPLY_LENGTH)
    ]


@dataclass(frozen=True)
class CoachDecision:
    """The turn's observable decision: no reasoning, only its outcome."""

    intent: Intent
    decision: Decision
    # the Formiq tools that returned data in this turn, in the order first used
    tools_used: tuple[str, ...]


def data_status(result: dict[str, Any]) -> DataStatus:
    output, error = result.get("output"), result.get("error")
    if isinstance(output, dict):
        return DataStatus.INCOMPLETE if output.get("truncated") else DataStatus.AVAILABLE
    if isinstance(error, dict):
        if error.get("code") in MISSING_ERROR_CODES:
            return DataStatus.MISSING
        return DataStatus.FAILED
    return DataStatus.UNEXPECTED


def has_data(result: ToolResult) -> bool:
    return data_status(result.result) in (DataStatus.AVAILABLE, DataStatus.INCOMPLETE)


def tools_used(results: Iterable[ToolResult]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(result.call.name for result in results if has_data(result)))


def check_decision(
    intent: Intent, decision: Decision, results: Sequence[ToolResult]
) -> str | None:
    """Why the decision cannot end the turn, given the turn's tool results; None
    when it can."""
    policy = POLICY[intent]
    if decision not in policy.decisions:
        allowed = ", ".join(sorted(policy.decisions))
        return f"{decision} is not a decision for a {intent} request; use one of: {allowed}"
    if decision is Decision.RETRIEVE_THEN_ANSWER and not any(
        has_data(result) for result in results if result.call.name in policy.data_tools
    ):
        tools = ", ".join(sorted(policy.data_tools))
        return (
            f"a {intent} answer needs data that {tools} returned in this turn, and none "
            "was returned: call the tool you need, or use ASK_CLARIFICATION or "
            "CANNOT_ANSWER"
        )
    return None


_NUMBER = re.compile(r"\d+")


def known_ids(user_message: str, results: Iterable[ToolResult]) -> set[int]:
    """The ids the turn may use: numbers the user wrote, and ids that tools
    returned in this turn."""
    ids = {int(number) for number in _NUMBER.findall(user_message)}
    for result in results:
        if isinstance(result.result.get("output"), dict):
            ids.update(_ids_in(result.result["output"]))
    return ids


def _ids_in(value: Any) -> set[int]:
    if isinstance(value, dict):
        found = set()
        for key, item in value.items():
            if (key == "id" or key.endswith("_id")) and isinstance(item, int):
                found.add(item)
            else:
                found |= _ids_in(item)
        return found
    if isinstance(value, list):
        return set().union(*(_ids_in(item) for item in value))
    return set()


def ungrounded_ids(call: ToolCall, known: set[int]) -> list[str]:
    """The call's resource id arguments that neither the user nor a tool gave.

    user_id is not one of them: the tools reject it outright.
    """
    ungrounded = []
    for name, value in call.arguments.items():
        if not name.endswith("_id") or name == "user_id":
            continue
        number = _as_int(value)
        if number is not None and number not in known:
            ungrounded.append(f"{name}={number}")
    return ungrounded


def _as_int(value: Any) -> int | None:
    """The id as an integer, or None when it is not one (the tool rejects it)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None
