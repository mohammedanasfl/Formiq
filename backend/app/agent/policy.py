"""The coach's decision policy: what kind of request the user made, which Formiq
data its answer needs, and which decisions may end the turn.

The model ends every turn with a respond call that names the request's intent,
its decision and the reply. This module checks that decision against what the
turn actually retrieved, and against the safety backstop (app.agent.safety):
for a request the backstop flags, only the safe decisions in SAFETY_POLICY can
end the turn, whatever the model classified it as. It is pure and
deterministic: it sees the declared intent and decision, the reply and the tool
results, never the model's reasoning, and stores nothing.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, StringConstraints

from app.agent.safety import (
    SAFE_REPLIES,
    SafetyAssessment,
    SafetyCategory,
    unsafe_reply,
)
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
    # not about fitness: Formiq is a fitness coach, not a general assistant
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


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
_USER_DATA_TOOLS = frozenset(
    {
        "get_user_profile",
        "get_workout_plan",
        "get_workout_session",
        "get_current_workout_plan",
        "get_latest_workout_session",
    }
)

POLICY: dict[Intent, IntentPolicy] = {
    Intent.GENERAL_FITNESS: IntentPolicy(
        "General fitness knowledge (training, exercise, nutrition, recovery) that does not "
        "depend on the user's own data, such as what progressive overload is, or how you "
        "coach them. Not general knowledge outside fitness.",
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
        frozenset({"get_workout_plan", "get_current_workout_plan"}),
        frozenset({Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
    ),
    Intent.WORKOUT_HISTORY: IntentPolicy(
        "What the user actually did in a workout session: exercises, sets, reps, "
        "weights, effort, including comparing it with the plan.",
        frozenset({"get_workout_session", "get_latest_workout_session"}),
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
    Intent.OUT_OF_SCOPE: IntentPolicy(
        "Anything not about fitness, the user's Formiq data or how you coach them, such as "
        "general knowledge, technology, coding, news, trivia or jokes. Call no tools: "
        "Formiq gives its own short reply.",
        frozenset(),
        frozenset({Decision.CANNOT_ANSWER}),
    ),
}

# Formiq's reply to an OUT_OF_SCOPE request, whatever the model wrote: no
# general answer reaches the user, only the coach's scope.
OUT_OF_SCOPE_REPLY = (
    "I'm your Formiq fitness coach, so I can help with workouts, exercise, nutrition, "
    "recovery and your fitness progress. What would you like help with?"
)

# the tool error codes (app.tools) that mean the data does not exist for this user
MISSING_ERROR_CODES = frozenset({"USER_NOT_FOUND", "PROFILE_NOT_FOUND", "RESOURCE_NOT_FOUND"})

# the model's reply to the user; longer replies are rejected
MAX_REPLY_LENGTH = 8000


def respond_declaration(
    intents: Iterable[Intent] = Intent, decisions: Iterable[Decision] = Decision
) -> ToolDeclaration:
    """The respond tool, offering these intents and decisions."""
    return ToolDeclaration(
        name="respond",
        description=(
            "End your turn: give the request's intent, your decision and the reply the "
            "user will see. Call it alone, after any data you need has been returned. "
            "Formiq checks the decision against the data retrieved in this turn and tells "
            "you if it cannot be used."
        ),
        parameters={
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": [intent.value for intent in intents],
                    "description": "What kind of request the user made.",
                },
                "decision": {
                    "type": "string",
                    "enum": [decision.value for decision in decisions],
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


RESPOND = respond_declaration()


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
    # what the safety backstop found in the request; anything but SAFE means the
    # decision was one that SAFETY_POLICY allows
    safety: SafetyCategory = SafetyCategory.SAFE


@dataclass(frozen=True)
class SafetyPolicy:
    """How a turn ends when the safety backstop flags its request."""

    # the risk, for the model; never shown to the user as a label
    description: str
    # the only intents and decisions that can end the turn
    intents: frozenset[Intent]
    decisions: frozenset[Decision]
    # the turn's outcome when the model's cannot be used: Formiq's own reply
    fallback_intent: Intent
    fallback_decision: Decision
    fallback_reply: str

    @property
    def respond(self) -> ToolDeclaration:
        """The respond tool, offering only this policy's intents and decisions."""
        return respond_declaration(sorted(self.intents), sorted(self.decisions))


def _redirect(category: SafetyCategory, description: str) -> SafetyPolicy:
    return SafetyPolicy(
        description,
        frozenset({Intent.SAFETY_SENSITIVE}),
        frozenset({Decision.SAFE_REDIRECT}),
        Intent.SAFETY_SENSITIVE,
        Decision.SAFE_REDIRECT,
        SAFE_REPLIES[category],
    )


# The categories the backstop can flag. A flagged request ends with a safe
# redirect (or, when only the details are missing, a question): never ANSWER or
# RETRIEVE_THEN_ANSWER, and with no tools.
SAFETY_POLICY: dict[SafetyCategory, SafetyPolicy] = {
    SafetyCategory.PAIN_OR_INJURY: _redirect(
        SafetyCategory.PAIN_OR_INJURY,
        "pain beyond ordinary soreness, an injury, or a warning symptom such as chest "
        "pain, trouble breathing, dizziness or fainting",
    ),
    SafetyCategory.MEDICAL: _redirect(
        SafetyCategory.MEDICAL,
        "a medical question: a diagnosis, a medical condition, medication or treatment",
    ),
    SafetyCategory.DANGEROUS_EXERCISE: _redirect(
        SafetyCategory.DANGEROUS_EXERCISE,
        "exercising through pain or symptoms, or in a way that risks harm",
    ),
    SafetyCategory.EXTREME_WEIGHT_LOSS: _redirect(
        SafetyCategory.EXTREME_WEIGHT_LOSS,
        "weight loss much faster than is safe, or a crash diet",
    ),
    SafetyCategory.EXTREME_DIETING: _redirect(
        SafetyCategory.EXTREME_DIETING,
        "starvation, a very low calorie intake, a long fast or purging",
    ),
    SafetyCategory.INSUFFICIENT_SAFETY_CONTEXT: SafetyPolicy(
        "pain or discomfort whose kind and severity are unclear: it may be ordinary "
        "soreness, or something to have checked",
        frozenset({Intent.AMBIGUOUS, Intent.SAFETY_SENSITIVE}),
        frozenset({Decision.ASK_CLARIFICATION, Decision.SAFE_REDIRECT}),
        Intent.AMBIGUOUS,
        Decision.ASK_CLARIFICATION,
        SAFE_REPLIES[SafetyCategory.INSUFFICIENT_SAFETY_CONTEXT],
    ),
}

# Formiq's own labels: a safety reply showing one is not shown to the user.
INTERNAL_LABELS = frozenset({*Intent, *Decision, *SafetyCategory, *DataStatus})


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


def check_safety(
    assessment: SafetyAssessment, intent: Intent, decision: Decision, reply: str
) -> str | None:
    """Why the decision or its reply cannot end the turn, given what the safety
    backstop found in the request; None when it can.

    A flagged request allows only its SAFETY_POLICY decisions. Every redirect, and
    every reply to a flagged request, must also pass the reply check.
    """
    policy = SAFETY_POLICY.get(assessment.category)
    if policy is not None and (intent not in policy.intents or decision not in policy.decisions):
        allowed = ", ".join(sorted(policy.decisions))
        return (
            f"Formiq's safety check found {policy.description} in this request; use "
            f"intent {', '.join(sorted(policy.intents))} with one of: {allowed}"
        )
    if policy is not None or decision is Decision.SAFE_REDIRECT:
        return unsafe_reply(reply, INTERNAL_LABELS)
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
            if (key == "id" or key.endswith("_id")) and is_canonical_id(item):
                found.add(item)
            else:
                found |= _ids_in(item)
        return found
    if isinstance(value, list):
        return set().union(*(_ids_in(item) for item in value))
    return set()


def is_canonical_id(value: Any) -> bool:
    """Whether the value is a resource id in its one canonical form: a positive
    JSON integer. Never true or false (bool is an int in Python), a float such
    as 7.0, or a string such as "7", "+7", "07", " 7 ", "7.0", "1_0" or "1e1":
    those are not normalized into an id, so no other form of a grounded id can
    stand in for it."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def ungrounded_ids(call: ToolCall, known: set[int]) -> list[str]:
    """The call's resource id arguments that neither the user nor a tool gave:
    an id that is not canonical, or a canonical one that is not known. An id
    left out (None) is not one.

    user_id is not one of them: the tools reject it outright.
    """
    ungrounded = []
    for name, value in call.arguments.items():
        if not name.endswith("_id") or name == "user_id" or value is None:
            continue
        if not is_canonical_id(value) or value not in known:
            ungrounded.append(f"{name}={value!r}")
    return ungrounded
