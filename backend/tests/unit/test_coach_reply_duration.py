"""A reply states the workout's length as the proposal does (live Gemini pass of
2026-10-16, B3).

The live reply said "a 40-minute lower-body workout" while the card shown with
it said 26 minutes: the 40 was the time the user had asked for, which the
proposal was made within, and not how long the workout takes. The original F1
reply ("It takes about 20 minutes") sat beside a 23-minute card the same way.
Nothing compared the numbers. The proposal's own figures are in the turn's tool
result (Formiq works them out in code), so the reply check can: a length the
proposal does not have is rejected, and the model corrects it in its one retry.

The model and the tools are scripted. These tests prove what Formiq checks, not
how often Gemini misstates a number.
"""

import pytest

from app.agent import CANNOT_ANSWER_REPLY
from app.agent.graph import MAX_TOOL_ITERATIONS, PROPOSAL_RETRY_ROUNDS
from app.agent.policy import proposal_length, time_said
from app.agent.trust import (
    DURATION_TOLERANCE_MINUTES,
    REPLY_MISSTATES_DURATION,
    REPLY_PROBLEMS,
    ProposalLength,
    misstates_duration,
    reply_problem,
)
from app.ai import ToolCall, ToolResult
from app.observability.trajectory import EventType
from tests.coach import call, fake_provider, respond_turn, sent_contents, tool_responses, tool_turn
from tests.unit.test_coach_injection import COACH_INSTRUCTIONS, TOOL_NAMES
from tests.unit.test_coach_pending_replies import PENDING, pending_tools
from tests.unit.test_coach_proposal_budget import READS, propose, proposal_tools, run
from tests.unit.test_coach_trajectory import drive, events
from tests.unit.test_coach_unsupported_updates import LIVE_REPLY

# The live turns, word for word. T0 (the setup turn of the targeted F1 pass): the
# reply beside a 26-minute card, which was a 40-minute budget's workout.
T0_REPLY = (
    "I have put together a 40-minute lower-body workout for you using your dumbbells, tailored "
    "to help build muscle. It targets your lower body with squats, Romanian deadlifts, and "
    "calf raises, along with a warm-up and cool-down. You can review and approve it in Formiq "
    "to save it to your plan."
)
# and the card shown with it: 3 minutes of warm-up, 18 of main work, 5 of cool-down
T0_CARD = ProposalLength(26, (3, 18, 5), (2, 3), (40,))
# the original F1 reply of the live pass (B5), beside the unchanged 23-minute card
B5_CARD = ProposalLength(23, (3, 16, 4), (2, 3), ())

# the recorded card of T0 as a proposal's tool result
PROPOSED_26 = {
    "output": {
        "status": "awaiting_user_approval",
        "name": "Lower Body Dumbbell & Band Workout",
        "estimated_minutes": 26,
        "warm_up_minutes": 3,
        "main_minutes": 18,
        "cool_down_minutes": 5,
        "exercises": [
            {"section": "WARM_UP", "exercise_name": "Marching in Place", "sets": 1, "duration_seconds": 120},
            {"section": "WARM_UP", "exercise_name": "Glute Bridge", "sets": 1, "reps": 10},
            {"section": "MAIN_WORKOUT", "exercise_name": "Bodyweight Squat", "sets": 3, "reps": 15},
            {"section": "MAIN_WORKOUT", "exercise_name": "Dumbbell Romanian Deadlift", "sets": 3, "reps": 12},
            {"section": "MAIN_WORKOUT", "exercise_name": "Standing Calf Raise", "sets": 3, "reps": 20},
            {"section": "COOL_DOWN", "exercise_name": "Brisk Walk", "sets": 1, "duration_seconds": 120},
            {"section": "COOL_DOWN", "exercise_name": "Figure-Four Glute Stretch", "sets": 1, "duration_seconds": 180},
        ],
    }
}
MESSAGE = "Now give me a lower-body day with the same stuff."
RIGHT = "I put together a lower-body workout that takes about 26 minutes. Review and approve it in Formiq."


# --- the rule: what a reply may say of the length ---


def test_the_recorded_40_minute_reply_beside_a_26_minute_card_is_rejected():
    assert misstates_duration(T0_REPLY, T0_CARD)
    assert (
        reply_problem(T0_REPLY, COACH_INSTRUCTIONS, TOOL_NAMES, proposed=True, length=T0_CARD)
        == REPLY_MISSTATES_DURATION
    )
    assert REPLY_PROBLEMS[REPLY_MISSTATES_DURATION] == "duration_mismatch"


def test_the_original_20_minute_claim_beside_a_23_minute_card_is_rejected():
    assert misstates_duration(LIVE_REPLY, B5_CARD)
    # as the claim of a workout that was made, with the update claim taken out
    made = "Here is your lower-body workout. It takes about 20 minutes to build muscle."
    assert misstates_duration(made, B5_CARD)


@pytest.mark.parametrize(
    "reply",
    [
        "It takes about 26 minutes.",
        "The whole workout takes about 26 minutes in total.",
        "A 26-minute lower-body workout.",
        "It is a 26 minute session.",
        "This lower body workout takes around 24 minutes.",  # within two minutes
        "It takes roughly 28 minutes.",
        "The workout runs 26 minutes from start to finish.",
        "About 26 minutes in all, and you can approve it in Formiq.",
        "It takes about 25-30 minutes.",
        "It takes under 30 minutes.",
        "It takes at least 20 minutes.",
        "It's estimated at about 26 mins.",
    ],
)
def test_the_proposals_own_length_passes_within_the_rounding_tolerance(reply):
    assert DURATION_TOLERANCE_MINUTES == 2
    assert not misstates_duration(reply, T0_CARD), reply


@pytest.mark.parametrize(
    "reply",
    [
        "It takes about 29 minutes.",  # three off
        "It takes about 23 minutes.",
        "A 40-minute workout.",
        "It takes about 40 minutes in total.",
        "The workout lasts 45 minutes.",
        "It is 20 minutes long.",
        "A 30 min session.",
        "It takes under 20 minutes.",
        "It takes at least 40 minutes.",
        "It takes about 20-22 minutes.",  # a range that does not reach it
        "It will take you about 40 minutes.",
    ],
)
def test_a_length_the_proposal_does_not_have_is_rejected(reply):
    assert misstates_duration(reply, T0_CARD), reply


@pytest.mark.parametrize(
    "reply",
    [
        "The warm-up takes about 3 minutes, the main work about 18 and the cool-down about 5.",
        "It has a 5 minute cool-down.",
        "Start with 2 minutes of marching in place.",
        "The cool-down is 5 minutes and the main part takes about 18 minutes.",
        "The walk takes 2 minutes and the stretch takes 3 minutes.",
        "The main workout takes about 19 minutes.",  # a minute off a section
    ],
)
def test_the_sections_and_timed_exercises_own_minutes_pass(reply):
    assert not misstates_duration(reply, T0_CARD), reply


@pytest.mark.parametrize(
    "reply",
    [
        "The warm-up takes about 10 minutes.",  # it takes 3
        "The cool-down is 12 minutes.",
    ],
)
def test_a_wrong_section_length_is_rejected_too(reply):
    assert misstates_duration(reply, T0_CARD), reply


@pytest.mark.parametrize(
    "reply",
    [
        # the user's time, named as theirs, beside the workout's own
        "It fits within the 40 minutes you have, and takes about 26 minutes.",
        "You have 40 minutes, so this one is 26 minutes and leaves some time to spare.",
        "That is under the 40 minutes you asked for.",
        "The workout takes about 26 minutes, well inside your 40 minutes.",
        "With the 40 minutes you mentioned, it should be easy to fit.",
        # nothing here is a claim of the workout's length
        "Rest 2 minutes between sets.",
        "Hold the stretch for 1 minute on each side.",
        "Warm up for 10 minutes before you start, if you like.",  # advice, not the proposal's
        "I would aim for a workout of about forty minutes next week.",  # no figure to read
        "Your lower-body workout is ready to review and approve in Formiq.",
        "",
    ],
)
def test_the_time_the_user_has_and_other_figures_are_not_claims_about_the_workouts_length(reply):
    assert not misstates_duration(reply, T0_CARD), reply


def test_the_users_budget_does_not_excuse_calling_the_workout_that_long():
    # the budget is 40; the workout is 26: "a 40-minute workout" is a claim about the workout
    assert misstates_duration("Here is your 40-minute workout.", T0_CARD)
    assert misstates_duration("Here is a 40-minute workout that fits the 40 minutes you have.", T0_CARD)
    # and a figure that is not the user's, named as the time they have, is read as a claim
    assert misstates_duration("It takes about 35 minutes, within the time you have.", T0_CARD)


def test_a_budget_figure_only_stands_when_it_is_named_as_the_users_time():
    # 40 is the user's; but "takes about 40 minutes" says nothing of having it
    assert misstates_duration("It takes about 40 minutes.", T0_CARD)
    assert misstates_duration("The workout takes you 40 minutes.", T0_CARD)


# --- where the figures come from: Formiq's own result, never the model's words ---


def result(name, value, **arguments):
    return ToolResult(call=ToolCall(name=name, arguments=arguments), result=value)


def test_the_figures_of_an_accepted_proposal_are_those_of_its_result():
    length = proposal_length(
        [result("propose_workout_plan", PROPOSED_26, max_minutes=40)], [], ["Give me 40 minutes."]
    )

    assert length == ProposalLength(26, (3, 18, 5), (2, 3), (40,))


def test_the_time_a_proposal_was_made_for_and_the_users_words_are_the_budget_not_the_length():
    length = proposal_length(
        [result("propose_workout_plan", PROPOSED_26, max_minutes=35)],
        [],
        ["I have 30 minutes, or maybe 25-30 min", "an hour and a half is too long", "1.5 hours free"],
    )

    assert length.estimated == 26
    assert set(length.budget) == {30, 25, 90, 35}


def test_the_proposal_awaiting_approval_that_the_turn_read_gives_the_figures_too():
    pending = {"output": {**PENDING["output"], **PROPOSED_26["output"]}}

    length = proposal_length([], [result("get_pending_proposal", pending)])

    assert length == ProposalLength(26, (3, 18, 5), (2, 3), ())


def test_an_accepted_proposal_is_the_one_shown_before_one_that_was_waiting():
    other = {"output": {**PENDING["output"], "estimated_minutes": 99, "warm_up_minutes": 9}}

    length = proposal_length(
        [result("propose_workout_plan", PROPOSED_26)], [result("get_pending_proposal", other)]
    )

    assert length.estimated == 26


@pytest.mark.parametrize(
    "refused",
    [
        {"error": {"code": "INVALID_INPUT", "message": "..."}},
        {"output": {"status": "awaiting_user_approval", "estimated_minutes": "26"}},  # not a number
        {"output": {"status": "awaiting_user_approval"}},  # no figures
    ],
)
def test_there_are_no_figures_to_hold_a_reply_to_without_an_accepted_proposal(refused):
    assert proposal_length([result("propose_workout_plan", refused)], []) is None
    assert proposal_length([], []) is None


def test_a_proposal_the_turn_read_without_figures_checks_nothing():
    # the fixtures of the older tests have none: nothing is rejected on their account
    assert proposal_length([], [result("get_pending_proposal", PENDING)]) is None


def test_the_users_time_is_read_in_minutes_and_hours():
    assert time_said(["I have 40 minutes", "25-30 min", "just 1 hr", "2.5 hours"]) == (
        40, 25, 30, 60, 150,
    )
    assert time_said(["3 sets of 12", "week 40"]) == ()


# --- in the turn: one retry corrects it, and a reply that matches costs nothing ---


def made(*replies, intent="ADAPTATION"):
    """A model that reads, searches, proposes, then gives these replies in turn."""
    return fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        *(respond_turn(reply, intent, "RETRIEVE_THEN_ANSWER") for reply in replies),
    )


def test_a_reply_that_matches_the_proposal_costs_no_extra_model_request():
    provider = made(RIGHT)

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == RIGHT


def test_the_recorded_40_minute_reply_is_rejected_once_and_a_correct_one_is_shown():
    provider = made(T0_REPLY, RIGHT)

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert provider.generate_turn.call_count == 4  # the one retry
    assert state["final_response"] == RIGHT
    (rejection,) = [
        item.response["error"]
        for item in tool_responses(sent_contents(provider, 3)[-1])
        if item.name == "respond"
    ]
    assert rejection["code"] == "DECISION_REJECTED"
    # the model is told the proposal's own figures, so one retry can correct it
    assert rejection["message"].startswith(REPLY_MISSTATES_DURATION)
    assert "about 26 minutes" in rejection["message"] and "3, 18, 5" in rejection["message"]


def test_the_rejection_is_recorded_as_a_duration_mismatch_and_a_reply_rejection():
    provider = made(T0_REPLY, RIGHT)

    _, trace, _ = drive(provider, proposal_tools(PROPOSED_26), MESSAGE)

    (rejected,) = events(trace, EventType.REPLY_REJECTED)
    assert rejected["category"] == "duration_mismatch"
    assert trace.trajectory.summary()["validation"]["reply_rejections"] == 1


def test_a_model_that_keeps_misstating_the_length_ends_within_the_bounds():
    provider = made(*([T0_REPLY] * 8))

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert provider.generate_turn.call_count <= MAX_TOOL_ITERATIONS + PROPOSAL_RETRY_ROUNDS + 1
    # the wrong length never reached the user: the turn ends with Formiq's own reply, which
    # says the proposal's own figures (the proposal Formiq accepted is shown: see
    # test_coach_accepted_proposal_fallback)
    assert state["final_response"] != CANNOT_ANSWER_REPLY
    assert "40-minute" not in state["final_response"]
    assert "about 26 minutes in all" in state["final_response"]


def test_the_time_the_user_has_is_not_taken_for_the_workouts_length():
    message = "Build me a lower-body workout, I have 40 minutes."
    reply = "It fits within the 40 minutes you have: about 26 minutes with the warm-up and cool-down."
    provider = made(reply)

    state = run(provider, proposal_tools(PROPOSED_26), message)

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == reply


def test_the_users_40_minutes_does_not_make_a_40_minute_workout_of_a_26_minute_one():
    message = "Build me a lower-body workout, I have 40 minutes."
    provider = made("Here is your 40-minute lower-body workout.", RIGHT)

    state = run(provider, proposal_tools(PROPOSED_26), message)

    assert provider.generate_turn.call_count == 4
    assert state["final_response"] == RIGHT


def test_every_intent_that_ends_a_proposal_turn_is_held_to_the_figures():
    for intent in ("ADAPTATION", "DAILY_WORKOUT", "WORKOUT_PLAN"):
        provider = made(T0_REPLY, RIGHT, intent=intent)

        state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

        assert state["final_response"] == RIGHT, intent


def test_a_reply_that_is_not_shown_with_a_proposal_is_not_held_to_its_figures():
    # a turn that ends with a question shows no card: no length to check against
    provider = fake_provider(
        tool_turn(*(call(name) for name in READS), call("search_exercises", use="MAIN_WORKOUT")),
        tool_turn(propose(10, 11)),
        respond_turn("A 40-minute workout needs more equipment.", "ADAPTATION", "ASK_CLARIFICATION"),
    )

    state = run(provider, proposal_tools(PROPOSED_26), MESSAGE)

    assert provider.generate_turn.call_count == 3
    assert state["final_response"] == "A 40-minute workout needs more equipment."


# --- a follow-up about the proposal awaiting approval ---


def follow_up(reply, *, then=()):
    provider = fake_provider(
        tool_turn(call("get_pending_proposal")),
        respond_turn(reply, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER"),
        *(respond_turn(item, "WORKOUT_PLAN", "RETRIEVE_THEN_ANSWER") for item in then),
    )
    figures = {"output": {**PENDING["output"], **PROPOSED_26["output"]}}
    state = run(
        provider, pending_tools(figures), "How long will the whole workout take?",
        proposal_awaiting_approval=True,
    )
    return provider, state


def test_a_truthful_follow_up_about_the_length_costs_no_extra_request():
    reply = "The whole workout takes about 26 minutes. You can review and approve it in Formiq."

    provider, state = follow_up(reply)

    assert provider.generate_turn.call_count == 2
    assert state["final_response"] == reply


def test_a_follow_up_that_misstates_the_length_is_corrected_in_one_retry():
    provider, state = follow_up(
        "The whole workout takes about 40 minutes. You can review and approve it in Formiq.",
        then=["It takes about 26 minutes in all. You can review and approve it in Formiq."],
    )

    assert provider.generate_turn.call_count == 3
    assert "26 minutes" in state["final_response"]
