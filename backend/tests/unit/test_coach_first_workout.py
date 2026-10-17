"""A first workout for a user with no plan (live Gemini pass of 2026-10-16, B2).

The live turn: a user with no saved plan and nothing awaiting approval asked for
a workout. Formiq accepted the proposal at the second model request, and then
the model's respond call (intent WORKOUT_PLAN) was rejected: that intent needs
data from a plan read or the proposal awaiting approval, and the proposal the
turn had just made is kept only once the turn ends, so no read could return
it. The model followed the rejection to get_pending_proposal (empty), proposed
again (not run: a turn makes one), and the decision round was rejected too: six
model requests, 52.8K tokens, a generic failure and the accepted proposal
discarded.

These tests drive the real graph with a scripted model and scripted tools, and
prove what Formiq enforces: a proposal it accepted is evidence for the plan
intent and for nothing else, one it refused is no evidence, a turn still
accepts one proposal and ends within its bounds, and the telemetry says what
happened. They do not prove how Gemini chooses an intent.
"""

import pytest

from app.agent import CANNOT_ANSWER_REPLY, MAX_TOOL_ITERATIONS
from app.agent.graph import PROPOSAL_RETRY_ROUNDS, proposed
from app.observability.trajectory import EventType
from tests.coach import (
    call,
    fake_provider,
    respond_turn,
    sent_contents,
    tool_responses,
    tool_turn,
)
from tests.unit.test_coach_proposal_budget import ACCEPTED, MISSING_CORE, READS, propose, run
from tests.unit.test_coach_recovery import NONE_YET, tools_where
from tests.unit.test_coach_trajectory import drive, events, summary_of

MESSAGE = "Build me an upper-body workout for 40 minutes."
REPLY = "Here is an upper-body workout to review and approve in Formiq."
SEARCHES = (
    call("search_exercises", use="MAIN_WORKOUT"),
    call("search_exercises", use="WARM_UP"),
    call("search_exercises", use="COOL_DOWN"),
)
# a user with no saved plan and no workout yet: the reads find none
NEW_USER = {"get_current_workout_plan": NONE_YET, "get_latest_workout_session": NONE_YET}
MAX_REQUESTS = MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1


def first_round():
    """The live turn's first request: the reads and the three searches together."""
    return tool_turn(*(call(name) for name in READS), *SEARCHES)


def decide(intent, decision="RETRIEVE_THEN_ANSWER", reply=REPLY):
    return respond_turn(reply, intent, decision)


def test_a_new_user_gets_a_first_proposal_decided_as_a_plan_answer():
    tools = tools_where(NEW_USER, ACCEPTED)
    provider = fake_provider(first_round(), tool_turn(propose(10, 11)), decide("WORKOUT_PLAN"))

    state = run(provider, tools, MESSAGE)

    # three requests, as for an ADAPTATION or DAILY_WORKOUT decision: the first one is accepted
    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == REPLY
    assert (state["decision"].intent, state["decision"].decision) == (
        "WORKOUT_PLAN",
        "RETRIEVE_THEN_ANSWER",
    )
    assert "propose_workout_plan" in state["decision"].tools_used
    # nothing was read to find the proposal again, and the proposal ran once
    assert sum(names.count("propose_workout_plan") for names in tools.runs) == 1
    assert not any("get_pending_proposal" in names for names in tools.runs)


@pytest.mark.parametrize("intent", ["ADAPTATION", "DAILY_WORKOUT", "PROFILE"])
def test_the_other_intents_a_proposal_turn_may_end_with_are_unchanged(intent):
    tools = tools_where(NEW_USER, ACCEPTED)
    provider = fake_provider(first_round(), tool_turn(propose(10, 11)), decide(intent))

    state = run(provider, tools, MESSAGE)

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == REPLY


def test_a_refused_proposal_is_not_evidence_for_the_plan_intent():
    tools = tools_where(NEW_USER, MISSING_CORE)
    provider = fake_provider(
        first_round(),
        tool_turn(propose(10, 11)),  # refused, correctable
        decide("WORKOUT_PLAN", reply="Here is your workout."),  # nothing was proposed
        decide("WORKOUT_PLAN", "ASK_CLARIFICATION", "What equipment do you have?"),
    )

    state = run(provider, tools, MESSAGE)

    assert not proposed([m for m in state["messages"] if hasattr(m, "result")])
    (rejection,) = [
        response.response["error"]
        for response in tool_responses(sent_contents(provider, 3)[-1])
        if response.name == "respond"
    ]
    assert rejection["code"] == "DECISION_REJECTED"
    assert "none was returned" in rejection["message"]
    # the turn ends with the model's question, not with a claim about a workout
    assert state["final_response"] == "What equipment do you have?"
    assert state["decision"].decision == "ASK_CLARIFICATION"


def test_a_session_history_answer_is_still_refused_after_a_proposal():
    tools = tools_where(NEW_USER, ACCEPTED)
    provider = fake_provider(
        first_round(),
        tool_turn(propose(10, 11)),
        decide("WORKOUT_HISTORY"),  # no workout session was read
        decide("WORKOUT_PLAN"),
    )

    state = run(provider, tools, MESSAGE)

    (rejection,) = [
        response.response["error"]
        for response in tool_responses(sent_contents(provider, 3)[-1])
        if response.name == "respond"
    ]
    assert "get_latest_workout_session" in rejection["message"]
    assert provider.generate_turn.call_count == 4
    assert state["decision"].intent == "WORKOUT_PLAN" and state["final_response"] == REPLY


def test_a_model_that_keeps_choosing_the_wrong_intent_still_ends_within_the_bounds():
    tools = tools_where(NEW_USER, ACCEPTED)
    provider = fake_provider(
        first_round(),
        tool_turn(propose(10, 11)),
        *(decide("WORKOUT_HISTORY") for _ in range(MAX_REQUESTS)),
    )

    state = run(provider, tools, MESSAGE)

    assert provider.generate_turn.call_count <= MAX_REQUESTS
    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert state["decision"].decision == "CANNOT_ANSWER"


# --- one proposal a turn, and what the telemetry says of the second ---


def second_proposal_after_an_accepted_one():
    tools = tools_where(NEW_USER, ACCEPTED, ACCEPTED)
    provider = fake_provider(
        first_round(),
        tool_turn(propose(10, 11)),
        tool_turn(propose(10, 12)),  # a second one, though the first was accepted
        decide("WORKOUT_PLAN"),
    )
    return drive(provider, tools, MESSAGE), tools, provider


def test_a_second_proposal_is_not_run_and_the_first_stays_the_turns_proposal():
    (state, trace, _), tools, provider = second_proposal_after_an_accepted_one()

    assert sum(names.count("propose_workout_plan") for names in tools.runs) == 1
    (refusal,) = [
        response.response["error"]
        for response in tool_responses(sent_contents(provider, 3)[-1])
        if response.name == "propose_workout_plan"
    ]
    assert refusal["code"] == "PROPOSAL_LIMIT"
    assert "already accepted a proposal in this turn" in refusal["message"]
    assert state["final_response"] == REPLY
    assert summary_of(trace)["proposal"]["accepted_in_request"] == 2


def test_a_second_proposal_is_recorded_as_a_limit_and_not_as_a_rejection_of_the_workout():
    (_, trace, _), _, _ = second_proposal_after_an_accepted_one()

    summary = summary_of(trace)
    # two attempts; the second was never judged, so there is no rejection
    assert summary["proposal"]["attempts"] == 2 and summary["proposal"]["rejections"] == 0
    assert events(trace, EventType.PROPOSAL_VALIDATION_REJECTED) == []
    (blocked,) = events(trace, EventType.TOOL_CALL_BLOCKED)
    assert (blocked["tool"], blocked["category"]) == ("propose_workout_plan", "proposal_limit")
    assert "proposal_limit" in summary["failure_reasons"]
    assert "proposal_rejected_irrecoverable" not in summary["failure_reasons"]
    assert summary["validation"]["decision_rejections"] == 0


def test_two_proposals_in_one_round_record_the_second_as_a_limit_too():
    tools = tools_where(NEW_USER, ACCEPTED, ACCEPTED)
    provider = fake_provider(
        first_round(),
        tool_turn(propose(10, 11), propose(10, 12)),
        decide("WORKOUT_PLAN"),
    )

    _, trace, _ = drive(provider, tools, MESSAGE)

    (blocked,) = events(trace, EventType.TOOL_CALL_BLOCKED)
    assert blocked["category"] == "proposal_limit"
    assert summary_of(trace)["proposal"]["rejections"] == 0


def test_a_refusal_proposing_again_cannot_fix_is_still_an_irrecoverable_rejection():
    no_profile = {"error": {"code": "PROFILE_NOT_FOUND", "message": "no fitness profile"}}
    tools = tools_where({**NEW_USER, "get_user_profile": no_profile})
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS)),
        tool_turn(propose(10, 11)),
        decide("DAILY_WORKOUT", "ASK_CLARIFICATION", "Tell me about your experience."),
    )

    _, trace, _ = drive(provider, tools, MESSAGE, status="clarification")

    summary = summary_of(trace)
    assert summary["proposal"]["rejections"] == 1
    (rejected,) = events(trace, EventType.PROPOSAL_VALIDATION_REJECTED)
    assert rejected["category"] == "proposal_rejected_irrecoverable"
