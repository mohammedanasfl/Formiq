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
from app.agent.trust import ProposalLength
from app.ai import ToolCall, ToolDeclaration, ToolResult


class Intent(StrEnum):
    GENERAL_FITNESS = "GENERAL_FITNESS"
    PROFILE = "PROFILE"
    WORKOUT_PLAN = "WORKOUT_PLAN"
    WORKOUT_HISTORY = "WORKOUT_HISTORY"
    EXERCISE = "EXERCISE"
    ADAPTATION = "ADAPTATION"
    DAILY_WORKOUT = "DAILY_WORKOUT"
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
    # The tools RETRIEVE_THEN_ANSWER requires to have been checked in this turn,
    # each one: it returned data, or that there is none. A failed or compacted
    # result is not a check, so nothing is assumed about what it would hold.
    checked_tools: frozenset[str] = frozenset()


# ASK_CLARIFICATION, SAFE_REDIRECT and CANNOT_ANSWER answer nothing from data, so
# they suit any request that is not safety-sensitive or ambiguous.
_FALLBACKS = frozenset(
    {Decision.ASK_CLARIFICATION, Decision.SAFE_REDIRECT, Decision.CANNOT_ANSWER}
)
_USER_DATA_TOOLS = frozenset(
    {
        "get_user_profile",
        "get_workout_plan",
        "list_workout_plans",
        "get_workout_session",
        "get_current_workout_plan",
        "get_latest_workout_session",
        "get_pending_proposal",
    }
)

# The reads a proposal rests on, in the order Formiq loads them: the profile it
# is built for, the current plan it must not duplicate, and the last workout it
# must not train again. The same three a recommendation for today rests on.
PROPOSAL_CONTEXT = ("get_user_profile", "get_current_workout_plan", "get_latest_workout_session")

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
        "The user's workout plans: what one prescribes, which plans they have, the "
        "workout you proposed that awaits their approval, or the workout you propose "
        "in this turn.",
        # propose_workout_plan counts only when Formiq accepted the proposal (its
        # result is data): it is the workout the user is shown, which no read can
        # return yet, since a proposal is kept only once the turn ends. A user with
        # no saved plan and nothing awaiting approval has no other evidence for it.
        frozenset(
            {
                "get_workout_plan",
                "get_current_workout_plan",
                "list_workout_plans",
                "get_pending_proposal",
                "propose_workout_plan",
            }
        ),
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
    Intent.DAILY_WORKOUT: IntentPolicy(
        "What the user should do today or in their next workout: their planned workout, "
        "a shorter or lighter version of it, or rest, including around limited time, "
        "tiredness or a missed workout. Answering it needs their profile, current plan and "
        "last workout checked in this turn, together.",
        _USER_DATA_TOOLS,
        frozenset({Decision.RETRIEVE_THEN_ANSWER}) | _FALLBACKS,
        checked_tools=frozenset(PROPOSAL_CONTEXT),
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

# Words that make a request about fitness, whatever else it says: an OUT_OF_SCOPE
# decision for it is rejected (check_scope), so a workout, equipment or body
# request is never met with Formiq's redirect. Only words that are about
# fitness in a coach's conversation, never ordinary words with other senses
# ("training", "running", "sets", "weights", "plan", "back", "core").
_FITNESS_WORDS = re.compile(
    r"\b(?:work[- ]?outs?|exercis(?:e|es|ing)|gym|fitness|equipment|dumb[- ]?bells?|"
    r"barbells?|kettle[- ]?bells?|resistance bands?|push[- ]?ups?|pull[- ]?ups?|chin[- ]?ups?|"
    r"sit[- ]?ups?|squats?|lunges?|planks?|deadlifts?|burpees?|warm[- ]?ups?|cool[- ]?downs?|"
    r"cardio|stretch(?:es|ing)?|muscles?|abs|glutes|biceps|triceps|hamstrings?|quads|"
    r"neck|mobility|reps|strength training|weight[- ]?lifting|lose weight|weight loss|"
    r"protein|calories|diet|nutrition|macros|jogging|soreness)\b",
    re.IGNORECASE,
)
# A short follow-up asking to change something just discussed: in a coach's
# conversation, about the workout ("make it shorter", "an easier alternative").
_FOLLOW_UP_WORDS = re.compile(
    r"\b(?:shorter|longer|easier|harder|lighter|heavier|simpler|alternatives?|swap|"
    r"replace|rewrite|revise|adjust|intensity)\b",
    re.IGNORECASE,
)
_FOLLOW_UP_MAX_WORDS = 12


def fitness_terms(message: str, has_conversation: bool) -> list[str]:
    """The words that make the message about fitness: fitness words, or, in a
    conversation, a short follow-up asking to change what was discussed."""
    terms = list(dict.fromkeys(match.casefold() for match in _FITNESS_WORDS.findall(message)))
    if has_conversation and len(message.split()) <= _FOLLOW_UP_MAX_WORDS:
        terms += [
            match.casefold()
            for match in _FOLLOW_UP_WORDS.findall(message)
            if match.casefold() not in terms
        ]
    return terms


def check_scope(intent: Intent, terms: Sequence[str]) -> str | None:
    """Why an OUT_OF_SCOPE decision cannot end the turn: the request is about
    fitness (terms, from fitness_terms()). None when it can, or the intent is
    another. Formiq's redirect is for requests outside fitness only; one it
    cannot do, or that is unsafe, is answered as what it is."""
    if intent is not Intent.OUT_OF_SCOPE or not terms:
        return None
    named = ", ".join(repr(term) for term in terms[:3])
    return (
        f"this request is about fitness (it says {named}), so it is not OUT_OF_SCOPE: use "
        "the intent that fits it. If Formiq cannot do what it asks, say so in your own reply, "
        "with what it can do instead, as CANNOT_ANSWER or ASK_CLARIFICATION; if it is risky, "
        "SAFETY_SENSITIVE"
    )


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


# what a check of a tool may find: its data, or that there is none
_CHECKED = frozenset({DataStatus.AVAILABLE, DataStatus.INCOMPLETE, DataStatus.MISSING})


def has_data(result: ToolResult) -> bool:
    return data_status(result.result) in (DataStatus.AVAILABLE, DataStatus.INCOMPLETE)


class ContextState(StrEnum):
    """Where one of the reads a proposal rests on stands in this turn. A read
    that failed says nothing about the data, so it is never the same as a read
    that found none."""

    # no result for it in this turn
    NOT_LOADED = "not_loaded"
    # read, and the data exists
    LOADED = "loaded"
    # read, and there is none: a user with no plan or no workout yet
    LOADED_EMPTY = "loaded_empty"
    # every attempt failed (or was compacted away from the evidence): not a check
    FAILED = "failed"


def context_states(results: Iterable[ToolResult]) -> dict[str, ContextState]:
    """The state of each of PROPOSAL_CONTEXT, from the turn's tool results: any
    successful read of it counts, whatever failed before or after."""
    found: dict[str, set[DataStatus]] = {name: set() for name in PROPOSAL_CONTEXT}
    for result in results:
        if result.call.name in found:
            found[result.call.name].add(data_status(result.result))
    states = {}
    for name, statuses in found.items():
        if statuses & {DataStatus.AVAILABLE, DataStatus.INCOMPLETE}:
            states[name] = ContextState.LOADED
        elif DataStatus.MISSING in statuses:
            states[name] = ContextState.LOADED_EMPTY
        elif statuses:
            states[name] = ContextState.FAILED
        else:
            states[name] = ContextState.NOT_LOADED
    return states


@dataclass(frozen=True)
class ContextGap:
    """What stands between the turn and a proposal: the reads not made, the
    reads that failed, and whether the profile is missing for good."""

    not_loaded: tuple[str, ...] = ()
    failed: tuple[str, ...] = ()
    # the profile was read and there is none: the plan has nothing to be built for
    no_profile: bool = False

    @property
    def ok(self) -> bool:
        return not (self.not_loaded or self.failed or self.no_profile)

    @property
    def message(self) -> str | None:
        """What the model is told, or None when nothing stands in the way."""
        if unchecked := sorted((*self.not_loaded, *self.failed)):
            failed = (
                f" ({', '.join(sorted(self.failed))} failed: a read that failed is not a check)"
                if self.failed
                else ""
            )
            return (
                f"check {', '.join(unchecked)} before proposing a plan{failed}: a suitable "
                "planned workout is recommended, not duplicated"
            )
        if self.no_profile:
            return (
                "the user has no fitness profile to build a plan for: ask about their "
                "experience and equipment, or suggest they set up their profile"
            )
        return None


def proposal_context_gap(results: Iterable[ToolResult]) -> ContextGap:
    """What a proposal still needs, given the turn's tool results: like a
    recommendation for today, it rests on the profile, current plan and last
    workout checked in this turn, so a suitable plan is seen before another is
    made (a user with no plan or no workout yet is checked all the same); and
    it needs the profile's data, which the plan is built for."""
    states = context_states(results)
    return ContextGap(
        not_loaded=tuple(n for n in PROPOSAL_CONTEXT if states[n] is ContextState.NOT_LOADED),
        failed=tuple(n for n in PROPOSAL_CONTEXT if states[n] is ContextState.FAILED),
        no_profile=states["get_user_profile"] is ContextState.LOADED_EMPTY,
    )


def check_proposal(results: Sequence[ToolResult]) -> str | None:
    """Why a workout plan cannot be proposed yet, given the tool results of the
    turn so far; None when it can (proposal_context_gap())."""
    return proposal_context_gap(results).message


# The decisions that answer the user, and so may show them a proposal: the one the
# turn made, or the one awaiting their approval that the turn read again.
ANSWERS = frozenset({Decision.ANSWER, Decision.RETRIEVE_THEN_ANSWER})

# What a user says when they want a workout changed, not explained: the verbs
# for it, the words for a different one, and "make it ...". A question about
# the proposal ("why these?", "what changed?") has none of them.
_CHANGE_REQUEST = re.compile(
    r"\b(?:swap|replace|rewrite|revise|adjust|modify|redo|rework|alter|tweak|update|shorten|"
    r"lengthen|shorter|longer|easier|harder|lighter|heavier|simpler|different|another|"
    r"alternatives?|instead|remove|drop|add|fewer|more|less|without|cancel|reschedule|move)\b"
    r"|\bchange\s+(?:it|this|that|the|my|these|those|them)\b"
    r"|\bmake\s+(?:it|this|that|them)\b",
    re.IGNORECASE,
)


# What a user says when something about the workout does not suit them, without
# asking for a change in so many words: what they lack or cannot do, what to
# leave out, an injury ("I don't have a bench", "nothing that needs a barbell",
# "my knee hurts"). The request is implied, and a reply that says it was met,
# in a turn that proposed nothing, is as false as one to "make it shorter".
_CONSTRAINT = re.compile(
    r"\b(?:avoid|skip|exclude|ditch|fix|accommodate|adapt|convert|trim|cut|reduce|increase|"
    r"extend|substitute|only|never|nothing|lack\w*|missing|injur\w*|hurt\w*|pain\w*|sore)\b"
    r"|\b(?:don['’]t|do\s+not|doesn['’]t|does\s+not|can['’]t|cannot|can\s+not|won['’]t|"
    r"haven['’]t|hasn['’]t|have\s+no|has\s+no|there['’]s\s+no|what\s+if|how\s+about)\b",
    re.IGNORECASE,
)

# What a user says to ask about the proposal they are shown, not to change it: a
# question (why, what, which, how, is it ...), or a request to explain, show or
# describe it. The message must begin so (after "ok", "so", "please"), so a
# statement ("I don't have a bench by the way") is never taken for one.
_ABOUT_PROPOSAL = re.compile(
    r"^\W*(?:(?:ok|okay|so|and|but|hey|hi|please|thanks|thank\s+you)\b\W*)*"
    r"(?:why|what|which|how|when|where|who|whose|is|are|was|were|does|do|did|will|"
    r"explain|show|tell|describe|walk|list|remind|summari[sz]e|recap|display|repeat|give\s+me|"
    r"(?:can|could|would)\s+(?:you|i)\s+(?:please\s+)?"
    r"(?:explain|show|see|tell|describe|walk|list|remind|summari[sz]e|recap|repeat|give\s+me)|"
    r"let\s+me\s+(?:see|know)|i(?:['’]d|\s+would)\s+like\s+(?:to\s+)?(?:see|know|understand|hear)|"
    r"i\s+want\s+to\s+(?:see|know|understand))\b",
    re.IGNORECASE,
)


def asks_for_change(message: str) -> bool:
    """Whether the user's message asks for a workout to be changed or replaced,
    or says something that calls for it (what they lack, cannot do or want left
    out), in words (the user's own, which the model cannot alter): then no
    reply may say it was, unless the turn proposed it. Words decide only this
    side of the question, and the worse mistake is the one that is not made:
    a message taken for a change request gets the strict reply check."""
    return _CHANGE_REQUEST.search(message) is not None or _CONSTRAINT.search(message) is not None


def asks_about_proposal(message: str) -> bool:
    """Whether the user's message is a question or a request to explain, show
    or describe, which is what a reply may answer by describing the proposal
    they are shown. A statement is not (asks_for_change() is the other side)."""
    return _ABOUT_PROPOSAL.search(message) is not None


def shown_pending_proposals(results: Iterable[ToolResult]) -> list[dict[str, Any]]:
    """What the turn read of the proposal awaiting the user's approval, in a
    form Formiq shows them again with the reply: one with its coverage recorded
    (an older proposal is not shown again, so its reply cannot point to it)."""
    return [
        output
        for result in results
        if result.call.name == "get_pending_proposal"
        and isinstance(output := result.result.get("output"), dict)
        and output.get("coverage") is not None
    ]


def pending_proposal_shown(results: Iterable[ToolResult]) -> bool:
    """Whether the turn read the proposal awaiting the user's approval in a form
    Formiq shows them again with the reply (shown_pending_proposals())."""
    return bool(shown_pending_proposals(results))


def pending_proposal_changes(results: Iterable[ToolResult]) -> tuple[str, ...]:
    """The exercises the proposal awaiting approval, as the turn read it, is
    recorded to add, remove or change against the saved plan (its own
    `changes`, worked out by Formiq): the only changes a reply can truthfully
    say the proposal holds when the turn proposed nothing."""
    names: list[str] = []
    for output in shown_pending_proposals(results):
        changes = output.get("changes")
        if not isinstance(changes, dict):
            continue
        for kind in ("added", "removed", "changed"):
            for item in changes.get(kind) or []:
                name = item.get("exercise_name") if isinstance(item, dict) else item
                if isinstance(name, str) and name:
                    names.append(name)
    return tuple(dict.fromkeys(names))


# the time a user says they have: "40 minutes", "25-30 min", "an hour and a half" is not read
_MINUTES_SAID = re.compile(r"(\d{1,3})(?:\s*(?:-|–|to)\s*(\d{1,3}))?\s*(?:minutes?|mins?)\b", re.I)
_HOURS_SAID = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:hours?|hrs?)\b", re.I)


def time_said(texts: Iterable[str]) -> tuple[int, ...]:
    """The minutes the user's words give, as figures: "40 minutes", "25-30
    min", "1.5 hours". What they have, not how long a workout takes."""
    figures: list[int] = []
    for text in texts:
        for match in _MINUTES_SAID.finditer(text):
            figures += [int(group) for group in match.groups() if group]
        figures += [round(float(hours) * 60) for hours in _HOURS_SAID.findall(text)]
    return tuple(dict.fromkeys(figures))


def proposal_length(
    earlier: Sequence[ToolResult], seen: Sequence[ToolResult], user_texts: Iterable[str] = ()
) -> ProposalLength | None:
    """How long the proposal the user is shown with the reply takes, from the
    turn's own tool results, as Formiq worked it out: the one Formiq accepted in
    the turn (the last), else the one awaiting approval that the turn read
    (shown_pending_proposals). None when there is none, or its figures are not
    there to be read: no reply is then checked against them. The time the user
    said they have (user_texts, and the time a proposal was made for) is kept
    apart: it is no figure of the workout's."""
    accepted = [
        result
        for result in earlier
        if result.call.name == "propose_workout_plan"
        and isinstance(result.result.get("output"), dict)
    ]
    made_for: list[int] = []
    if accepted:
        output = accepted[-1].result["output"]
        asked = accepted[-1].call.arguments.get("max_minutes")
        made_for = [asked] if isinstance(asked, int) and not isinstance(asked, bool) else []
    elif shown := shown_pending_proposals(seen):
        output = shown[-1]
    else:
        return None
    estimated = output.get("estimated_minutes")
    if not isinstance(estimated, int) or isinstance(estimated, bool):
        return None
    sections = tuple(
        value
        for name in ("warm_up_minutes", "main_minutes", "cool_down_minutes")
        if isinstance(value := output.get(name), int) and not isinstance(value, bool)
    )
    timed: set[int] = set()
    for item in output.get("exercises") or []:
        if not isinstance(item, dict):
            continue
        sets = item.get("sets") if isinstance(item.get("sets"), int) else 1
        for name in ("duration_seconds", "rest_seconds"):
            seconds = item.get(name)
            if isinstance(seconds, int) and seconds >= 60:
                timed.add(round(seconds / 60))
                if name == "duration_seconds":
                    timed.add(round(sets * seconds / 60))
    budget = (*time_said(user_texts), *made_for)
    return ProposalLength(estimated, sections, tuple(sorted(timed)), tuple(dict.fromkeys(budget)))


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
    if decision is Decision.RETRIEVE_THEN_ANSWER and (
        unchecked := policy.checked_tools
        - {result.call.name for result in results if data_status(result.result) in _CHECKED}
    ):
        return (
            f"a {intent} answer needs {', '.join(sorted(unchecked))} checked in this turn, "
            "and they were not: call them, together, then decide; if a call failed, use "
            "ASK_CLARIFICATION or CANNOT_ANSWER"
        )
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
    returned in this turn, in their data or in the catalog exercises Formiq
    suggested to correct a refused call."""
    ids = {int(number) for number in _NUMBER.findall(user_message)}
    for result in results:
        if isinstance(result.result.get("output"), dict):
            ids.update(_ids_in(result.result["output"]))
        elif isinstance(error := result.result.get("error"), dict) and isinstance(
            error.get("suggestions"), list
        ):
            ids.update(_ids_in(error["suggestions"]))
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
    """The call's resource id arguments, those in a list of records (such as a
    proposed plan's exercises) included, that neither the user nor a tool
    gave: an id that is not canonical, or a canonical one that is not known. An
    id left out (None) is not one.

    user_id is not one of them: the tools reject it outright.
    """
    ungrounded = []
    for name, value in _id_arguments(call.arguments):
        if name == "user_id" or value is None:
            continue
        if not is_canonical_id(value) or value not in known:
            ungrounded.append(f"{name}={value!r}")
    return ungrounded


def _id_arguments(arguments: dict[str, Any]) -> list[tuple[str, Any]]:
    found = []
    for name, value in arguments.items():
        if name.endswith("_id"):
            found.append((name, value))
        elif isinstance(value, list):
            for record in value:
                if isinstance(record, dict):
                    found += _id_arguments(record)
    return found
