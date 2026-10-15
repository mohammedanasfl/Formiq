"""Replies about a proposal that awaits the user's approval (app.agent.trust).

The live regression pass of 2026-10-15 saw the reply check reject the first
draft of three of four follow-ups ("Why did you choose these?", "Show me the
final proposal.", "What changed from my current plan?") as presenting a new
proposal: each cost one more model request, and each final answer was correct.
The check read words: "here is the proposal", "below", "I put together ..." all
look like a coach presenting something new.

What the check may know is not words but the turn: Formiq's own records say a
proposal awaits approval, the turn read it with get_pending_proposal, and
Formiq shows the user that same proposal again with the reply. For a user who
did not ask for a change, a reply then describes the proposal they are shown.
Still a claim, whatever the words: a new or changed workout made now, a
workout saved or approved, a new proposal when none was made, an exercise done
that no session shows.

The phrases below are modelled on the transcripts (the live drafts were not
captured: the traces hold metadata only). The model and the tools are scripted.
"""

import pytest

from app.agent.graph import CANNOT_ANSWER_REPLY, MAX_TOOL_ITERATIONS, PROPOSAL_RETRY_ROUNDS
from app.agent.trust import (
    REPLY_CLAIMS_APPROVAL,
    REPLY_CLAIMS_CHANGE,
    REPLY_CLAIMS_CREATION,
    REPLY_CLAIMS_NEW_PROPOSAL,
    REPLY_CLAIMS_UNDONE,
    reply_problem,
)
from tests.coach import call, fake_provider, respond_turn, tool_turn
from tests.unit.test_coach_injection import COACH_INSTRUCTIONS, TOOL_NAMES
from tests.unit.test_coach_proposal_budget import ScriptedTools, run

# --- the words alone: what a reply says, and what Formiq knows of the turn ---

# truthful: each only describes the proposal the user is shown
TRUTHFUL = [
    # "Show me the final proposal."
    "Here is the final proposal: a warm-up, four core exercises and a cool-down. It takes "
    "about 31 minutes, and you can review and approve it in Formiq.",
    "The proposal is below. It replaces your current Core & Ab Focus plan once you approve it.",
    # "Why did you choose these?"
    "I put together this workout around your core goal: Bird Dog and Ab Roller train your "
    "abs from different angles. You can review and approve it in Formiq.",
    "I designed the proposal for an intermediate level, and I added a warm-up and a cool-down "
    "so it fits your 30 minutes. Approve it in Formiq when you are ready.",
    "I've built the workout from exercises that need no bench, which is why the proposal "
    "has the Bird Dog.",
    # "Explain the second exercise."
    "Here is the second exercise of the proposal: the Ab Crunch Machine works your upper abs.",
    # "What changed from my current plan?"
    "Here are the differences. I replaced the 3/4 Sit-Up with the Bird Dog and I removed the "
    "Air Bike. You can review the proposal and approve it in Formiq.",
]


@pytest.mark.parametrize("reply", TRUTHFUL)
def test_the_unchanged_check_rejected_a_truthful_description_of_the_proposal(reply):
    # the failure the live pass saw: without the turn's facts, the words decide
    problem = reply_problem(reply, COACH_INSTRUCTIONS, TOOL_NAMES, awaiting_approval=True)

    assert problem in (REPLY_CLAIMS_NEW_PROPOSAL, REPLY_CLAIMS_CREATION, REPLY_CLAIMS_CHANGE), reply


@pytest.mark.parametrize("reply", TRUTHFUL)
def test_a_reply_describing_the_shown_proposal_passes_when_the_turn_read_it(reply):
    problem = reply_problem(
        reply, COACH_INSTRUCTIONS, TOOL_NAMES, awaiting_approval=True, explaining=True
    )

    assert problem is None, reply


# a new or changed workout, claimed in a turn that made none
FALSE_NEW = [
    "I've just created a new workout for you: Bird Dog, Plank and Crunches.",
    "Here is your new core workout, ready to approve in Formiq.",
    "I created a different workout with entirely new exercises.",
    "I've built another plan for you, with more core work.",
    "Your updated plan is ready: I swapped the plank for a dead bug.",
    "I just swapped the plank for a dead bug, so the proposal now has it.",
    "I went ahead and made it shorter; review the new version in Formiq.",
    "Approve the revised workout in Formiq.",
]


@pytest.mark.parametrize("reply", FALSE_NEW)
def test_a_new_or_changed_workout_is_still_a_false_claim_when_none_was_made(reply):
    for explaining in (False, True):
        problem = reply_problem(
            reply, COACH_INSTRUCTIONS, TOOL_NAMES, awaiting_approval=True, explaining=explaining
        )

        assert problem is not None, (explaining, reply)


@pytest.mark.parametrize(
    "reply", ["I've approved it for you.", "I have approved your proposal."]
)
def test_a_claimed_approval_is_rejected_while_explaining(reply):
    assert (
        reply_problem(reply, COACH_INSTRUCTIONS, TOOL_NAMES, awaiting_approval=True, explaining=True)
        == REPLY_CLAIMS_APPROVAL
    )


@pytest.mark.parametrize(
    "reply",
    [
        "I've saved your plan.",
        "I updated your workout.",
        "Your plan has been saved.",
        "I've added the proposal to your plans.",
    ],
)
def test_a_claimed_save_or_change_of_data_is_rejected_while_explaining(reply):
    problem = reply_problem(
        reply, COACH_INSTRUCTIONS, TOOL_NAMES, awaiting_approval=True, explaining=True
    )

    assert problem == REPLY_CLAIMS_CHANGE


def test_a_completed_exercise_the_session_shows_undone_is_rejected_while_explaining():
    problem = reply_problem(
        "You completed the Bird Dog last time, so the proposal keeps it.",
        COACH_INSTRUCTIONS,
        TOOL_NAMES,
        awaiting_approval=True,
        explaining=True,
        not_done=["Bird Dog"],
    )

    assert problem == REPLY_CLAIMS_UNDONE


def test_explaining_needs_a_proposal_that_awaits_approval():
    # whatever the caller says, with none awaiting, "the proposal" has nothing behind it
    problem = reply_problem(
        "The proposal is below.", COACH_INSTRUCTIONS, TOOL_NAMES, explaining=True
    )

    assert problem is not None


# --- the turn: Formiq decides whether the reply is an explanation ---

USER_PLAN = {"output": {"plan_id": 21, "name": "Core & Ab Focus"}}
PENDING = {
    "output": {
        "status": "awaiting_user_approval",
        "name": "Core & Ab Focus (Alternative)",
        "exercises": [
            {"exercise_order": 1, "section": "MAIN_WORKOUT", "exercise_name": "Bird Dog"},
            {"exercise_order": 2, "section": "MAIN_WORKOUT", "exercise_name": "Ab Crunch Machine"},
        ],
        "coverage": {"complete": True},
        "revision": {"kind": "ALTERNATIVE", "plan_id": 21},
        "changes": {"added": ["Bird Dog"], "removed": ["Air Bike"]},
    }
}
OLD_PENDING = {**PENDING, "output": {**PENDING["output"], "coverage": None}}


def pending_tools(result=PENDING):
    return ScriptedTools(lambda item: result if item.name == "get_pending_proposal" else USER_PLAN)


def follow_up(message, reply, *, result=PENDING, decision="RETRIEVE_THEN_ANSWER", more=()):
    """A turn that reads the pending proposal and answers: the model's requests
    and the final reply."""
    provider = fake_provider(
        tool_turn(call("get_pending_proposal")),
        respond_turn(reply, "WORKOUT_PLAN", decision),
        *more,
    )
    state = run(
        provider, pending_tools(result), message, proposal_awaiting_approval=True
    )
    return provider, state


@pytest.mark.parametrize(
    ("message", "reply"),
    [
        ("Show me the final proposal.", TRUTHFUL[0]),
        ("Why did you choose these?", TRUTHFUL[2]),
        ("Explain the second exercise.", TRUTHFUL[5]),
        ("What changed from my current plan?", TRUTHFUL[6]),
    ],
)
def test_a_truthful_explanation_costs_no_extra_model_request(message, reply):
    provider, state = follow_up(message, reply)

    assert provider.generate_turn.call_count == 2  # the read, then the answer
    assert state["final_response"] == reply


def test_the_same_reply_to_a_request_for_a_change_is_not_an_explanation():
    # the user asked for a change: a reply that says it was made, in a turn that made none
    reply = "I put together a shorter version below: I replaced the Ab Roller. Approve it in Formiq."
    provider, state = follow_up(
        "Can you make it shorter?",
        reply,
        more=(respond_turn("I can propose a shorter one if you like.", "WORKOUT_PLAN", "ASK_CLARIFICATION"),),
    )

    assert provider.generate_turn.call_count == 3  # rejected, then the honest answer
    assert state["final_response"] == "I can propose a shorter one if you like."


def test_a_proposal_that_formiq_does_not_show_again_cannot_be_pointed_to():
    # made before Formiq recorded coverage: not shown with the reply, so "below" is empty
    provider, state = follow_up(
        "Show me the final proposal.",
        "The proposal is below.",
        result=OLD_PENDING,
        more=(respond_turn("You have a proposal waiting for approval.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),),
    )

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == "You have a proposal waiting for approval."


def test_a_reply_that_does_not_answer_is_not_shown_with_the_proposal():
    # a question: Formiq shows the user no proposal with it, so nothing is below
    provider, state = follow_up(
        "Show me the final proposal.",
        "The proposal is below.",
        decision="ASK_CLARIFICATION",
        more=(respond_turn("Which proposal do you mean?", "WORKOUT_PLAN", "ASK_CLARIFICATION"),),
    )

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == "Which proposal do you mean?"


def test_a_turn_that_did_not_read_the_proposal_is_not_an_explanation():
    provider = fake_provider(
        tool_turn(call("get_current_workout_plan")),
        respond_turn("Here is the final proposal below.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        respond_turn("Your plan is Core & Ab Focus.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
    )

    state = run(provider, pending_tools(), "Show me the final proposal.", proposal_awaiting_approval=True)

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == "Your plan is Core & Ab Focus."


def test_a_false_claim_is_rejected_until_the_turns_limit_and_then_ends_cleanly():
    provider = fake_provider(
        tool_turn(call("get_pending_proposal")),
        *(
            respond_turn(
                "I've just created a new workout for you.", "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"
            )
            for _ in range(MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1)
        ),
    )

    state = run(
        provider, pending_tools(), "Why did you choose these?", proposal_awaiting_approval=True
    )

    assert state["final_response"] == CANNOT_ANSWER_REPLY
    assert provider.generate_turn.call_count <= MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
